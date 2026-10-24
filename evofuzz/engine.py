"""Deterministic evolutionary search; target-owned oracles establish failures."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import random

from . import protocol as p
from .config import Config
from .evolution import Corpus, Scheduler
from .runner import execute


class BudgetExhausted(Exception):
    pass


@dataclass
class Evaluator:
    config: Config
    binding: dict
    budget: int
    used: int = 0

    def call(self, name, actions):
        cfg = self.config
        payload = {"schema": "evofuzz/case/1", "case_id": p.digest(actions), "actions": actions}
        result = execute(cfg.commands[name], (p.canonical(payload) + "\n").encode(), cfg.root,
                         cfg.limits["timeout_ms"], cfg.limits["output_bytes"])
        if result.status != "completed":
            return {"transport": result.status}
        if result.code != 0:
            return {"transport": "exit", "code": result.code}
        try:
            return {"transport": "ok", "value": p.observation(p.loads(result.stdout))}
        except ValueError as exc:
            return {"transport": "protocol_error", "message": str(exc)}

    def evaluate(self, actions, target="target", reference=None):
        if self.used >= self.budget:
            raise BudgetExhausted
        self.used += 1
        cfg = self.config
        actions = p.case(actions, cfg.vocabulary, cfg.limits["max_actions"], cfg.domain)
        if cfg.fingerprint() != self.binding:
            return {"outcome": "error", "reason": "declared-input-drift"}
        actual = self.call(target, actions)
        oracle = self.call(reference or "oracle", actions) if reference or "oracle" in cfg.commands else None
        if cfg.fingerprint() != self.binding:
            return {"outcome": "error", "reason": "declared-input-drift"}
        if oracle and oracle["transport"] != "ok":
            return {"outcome": "error", "reason": "oracle-unavailable", "detail": oracle}
        if actual["transport"] == "exit":
            return failure("process-exit", str(actual["code"]), actual, oracle)
        if actual["transport"] != "ok":
            return {"outcome": "error", "reason": actual["transport"], "detail": actual}
        value = actual["value"]
        if value["status"] == "fail":
            return failure("property", value["failure"]["id"], actual, oracle)
        if oracle:
            other = oracle["value"]
            if (value["status"], value["observation"]) != (other["status"], other["observation"]):
                return failure("differential", "observation-mismatch", actual, oracle)
        return {"outcome": "invalid" if value["status"] == "invalid" else "pass",
                "coverage": sorted(set(value.get("coverage", []))),
                "distance": value.get("distance", 1_000_000), "target": actual, "oracle": oracle}


def failure(kind, identity, actual, oracle):
    return {"outcome": "failure", "signature": p.digest([kind, identity]), "kind": kind,
            "id": identity, "target": actual, "oracle": oracle}


def replay_receipts(results):
    return [{"outcome": r["outcome"], "signature": r.get("signature"),
             "result_sha256": p.digest(r)} for r in results]


def confirm(evaluator, actions, first=None, target="target", reference=None):
    first = first or evaluator.evaluate(actions, target, reference)
    results = [first]
    if first["outcome"] != "failure":
        return False, results
    for _ in range(evaluator.config.limits["confirmations"] - 1):
        repeated = evaluator.evaluate(actions, target, reference)
        results.append(repeated)
        if repeated.get("signature") != first["signature"]:
            return False, results
    return True, results


def shrink(evaluator, actions, signature, target="target", reference=None):
    """Bounded chunk deletion, ending with one-deletion minimality if completed."""
    current, granularity = copy.deepcopy(actions), 2
    start = evaluator.used
    cap = evaluator.config.limits["shrink_budget"]
    complete = True
    while current:
        chunk = max(1, (len(current) + granularity - 1) // granularity)
        changed = False
        for index in range(0, len(current), chunk):
            needed = evaluator.config.limits["confirmations"]
            if evaluator.used - start + needed > cap or evaluator.used + needed > evaluator.budget:
                complete = False
                break
            candidate = current[:index] + current[index + chunk:]
            verdict = evaluator.evaluate(candidate, target, reference)
            if verdict["outcome"] == "error":
                complete = False
                break
            if verdict.get("signature") == signature:
                reproduced, _ = confirm(evaluator, candidate, verdict, target, reference)
                if reproduced:
                    current, granularity, changed = candidate, max(2, granularity - 1), True
                    break
                complete = False
                break
        if not complete:
            break
        if changed:
            continue
        if chunk == 1:
            break
        granularity = min(len(current), granularity * 2)
    return current, {"evaluations": evaluator.used - start, "deletion_minimal": complete}


def mutate(rng, actions, vocabulary, max_actions, corpus, weights, domain=None, operator=None, donor=None):
    operators = domain.operators if domain else p.OPERATORS
    op = operator or rng.choices(operators, weights=[weights[x] for x in operators], k=1)[0]
    prefix_size = len(domain.setup) if domain else 0
    prefix, result = copy.deepcopy(actions[:prefix_size]), copy.deepcopy(actions[prefix_size:])
    available = max_actions - prefix_size
    def action():
        return domain.sample(rng) if domain else copy.deepcopy(rng.choice(vocabulary))
    if op in ("parameter", "rebind"):
        full = prefix + result
        getattr(domain, op)(rng, full)
        return full, op
    if op == "block":
        block = copy.deepcopy(rng.choice(domain.blocks)["actions"])
        if len(result) + len(block) <= available:
            index = rng.randrange(len(result) + 1)
            result[index:index] = block
    elif op == "random":
        result = [action() for _ in range(rng.randrange(available + 1))]
    elif op == "insert":
        result.insert(rng.randrange(len(result) + 1), action())
    elif not result:
        return prefix, op
    elif op == "replace":
        result[rng.randrange(len(result))] = action()
    elif op == "delete":
        del result[rng.randrange(len(result))]
    elif op == "duplicate":
        at = rng.randrange(len(result))
        result.insert(at, copy.deepcopy(result[at]))
    elif op == "swap":
        a, b = rng.randrange(len(result)), rng.randrange(len(result))
        result[a], result[b] = result[b], result[a]
    elif op == "splice":
        source = (donor if donor is not None else rng.choice(corpus))[prefix_size:]
        result = result[:rng.randrange(len(result) + 1)] + copy.deepcopy(source[rng.randrange(len(source) + 1):])
    return prefix + result[:available], op


def request(config, binding, corpus=None, feedback=None):
    archive = corpus if isinstance(corpus, Corpus) else Corpus(
        corpus or config.data["seeds"], config.limits["max_corpus"], config.archive)
    families = sorted(archive.summaries(), key=lambda f: (f["selections"], -f["reward"], f["family_id"]))[:8]
    packet = {"schema": "evofuzz/proposal-request/1", "objective": config.data["objective"],
              "target_id": p.digest(binding), "vocabulary": config.vocabulary,
              "max_actions": config.limits["max_actions"], "operators": list(config.operators),
              "domain": config.domain.data if config.domain else {}, "families": families,
              "corpus": [], "feedback": feedback or {},
              "instructions": "Return evofuzz/proposal/1 with this request_id, cases matching vocabulary prototypes/domain/setup, optional operator weights, family_weights for listed family IDs, and hypothesis. Do not change commands, oracle, objective, domain or bounds."}
    examples = [archive.records[identity]["actions"] for f in families for identity in f["cases"]]
    for actions in examples[:4]:
        candidate = packet | {"corpus": packet["corpus"] + [actions]}
        try:
            if len(p.canonical(candidate)) > 60_000:
                break
        except ValueError:
            break
        packet = candidate
    packet["request_id"] = p.digest(packet)
    return packet


def run(config, out, seed=0, budget=200, proposals=None, enable_proposer=False):
    p.integer(seed, 0, 2**63 - 1, "seed")
    p.integer(budget, 1, 100_000, "evaluation budget")
    p.require(not enable_proposer or "proposer" in config.commands, "no proposer configured")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    binding = config.fingerprint()
    p.write(out / "bindings.json", binding)
    p.write(out / "target.json", config.data)
    evaluator = Evaluator(config, binding, budget)
    rng = random.Random(seed)
    corpus = Corpus(config.data["seeds"], config.limits["max_corpus"], config.archive)
    queue = [(copy.deepcopy(a), "seed", None) for a in config.data["seeds"]]
    initial_request = request(config, binding)
    p.write(out / "request.json", initial_request)
    weights = dict.fromkeys(config.operators, 1)
    family_weights = {}
    scheduler = Scheduler(config.operators)
    events, findings, seen = [], [], set()
    signatures = set()
    recent_failures = []
    if proposals is not None:
        cases, changes = p.proposal(proposals, initial_request, config.vocabulary, config.limits["max_actions"], config.domain)
        queue = (queue + [(a, "proposal", initial_request["request_id"]) for a in cases])[:128]
        weights.update(changes)
        family_weights.update(proposals.get("family_weights", {}))
        p.write(out / "offline-proposal.json", proposals)
    attempts, proposer_calls, next_proposal = 0, 0, config.limits["proposer_interval"]
    status = "budget-complete"
    with (out / "cases.jsonl").open("w", encoding="utf-8") as log, (out / "lineage.jsonl").open("w", encoding="utf-8") as lineage:
        while evaluator.used < budget and attempts < budget * 8:
            if enable_proposer and evaluator.used >= next_proposal:
                packet = request(config, binding, corpus, {"evaluations": evaluator.used,
                                 "coverage": sorted(corpus.coverage)[:128], "findings": len(findings),
                                 "recent_failures": recent_failures})
                packet.pop("request_id")
                packet["learning"] = {f["family_id"]: scheduler.stats.get(f["family_id"], {}) for f in packet["families"][:4]}
                packet["request_id"] = p.digest(packet)
                proposer_calls += 1
                result = execute(config.commands["proposer"], (p.canonical(packet) + "\n").encode(),
                                 config.root, config.limits["proposer_timeout_ms"], config.limits["output_bytes"])
                record = {"request": packet, "transport": result.status}
                try:
                    p.require(result.status == "completed" and result.code == 0, "proposer execution failed")
                    proposed = p.loads(result.stdout)
                    cases, changes = p.proposal(proposed, packet, config.vocabulary, config.limits["max_actions"], config.domain)
                    queue = (queue + [(a, "proposal", packet["request_id"]) for a in cases])[:128]
                    weights.update(changes)
                    active = {r["family_id"] for r in corpus.records.values()}
                    family_weights = {k: v for k, v in (family_weights | proposed.get("family_weights", {})).items() if k in active}
                    record.update(status="accepted", proposal=proposed)
                except ValueError as exc:
                    record.update(status="rejected", reason=str(exc))
                p.write(out / f"proposal-{proposer_calls:04d}.json", record)
                next_proposal = evaluator.used + config.limits["proposer_interval"]
            attempts += 1
            parents, parent_events, generation, parent_family, donor = [], [], 0, None, None
            seed_waiting = bool(queue) and queue[0][1] == "seed"
            explored = False if seed_waiting else rng.randrange(100) < corpus.settings["exploration_percent"]
            if queue and not explored:
                actions, origin, proposal_id = queue.pop(0)
            else:
                parent = corpus.choose(rng, explored, family_weights)
                parent_family = parent["family_id"]
                origin = scheduler.choose(rng, parent_family, weights, explored)
                parents, generation = [parent["case_id"]], parent["generation"] + 1
                parent_events = [parent["event_id"]]
                if origin == "splice":
                    donor = copy.deepcopy(rng.choice(list(corpus.records.values())))
                    parents.append(donor["case_id"])
                    parent_events.append(donor["event_id"])
                    generation = max(generation, donor["generation"] + 1)
                actions, _ = mutate(rng, parent["actions"], config.vocabulary,
                                    config.limits["max_actions"], corpus.entries, weights,
                                    config.domain, origin, donor["actions"] if donor else None)
                if origin == "random":
                    parents, parent_events, generation = [], [], 0
                proposal_id = None
            case_id = p.digest(actions)
            descent = {"attempt": attempts, "event_id": f"attempt:{attempts}", "case_id": case_id,
                       "parents": parents, "parent_events": parent_events,
                       "operator": origin, "generation": generation, "exploration": explored,
                       "proposal_request_id": proposal_id}
            try:
                p.case(actions, config.vocabulary, config.limits["max_actions"], config.domain)
            except ValueError as exc:
                lineage.write(p.canonical(descent | {"status": "invalid", "reason": str(exc)}) + "\n")
                if parent_family:
                    scheduler.record(parent_family, origin, 0)
                continue
            if case_id in seen:
                lineage.write(p.canonical(descent | {"status": "duplicate"}) + "\n")
                if parent_family:
                    scheduler.record(parent_family, origin, 0)
                continue
            seen.add(case_id)
            verdict = evaluator.evaluate(actions)
            log.write(p.canonical({"actions": actions, "case_id": case_id, "origin": origin, "result": verdict}) + "\n")
            log.flush()
            selection = corpus.observe(actions, verdict, generation, descent["event_id"])
            lineage.write(p.canonical(descent | {"status": "executed", "selection": selection}) + "\n")
            lineage.flush()
            if parent_family:
                scheduler.record(parent_family, origin, selection["reward"])
                corpus.credit(parent_family, selection["reward"])
            if verdict["outcome"] == "error":
                status = "stopped-on-execution-error"
                events.append(verdict)
                break
            if verdict["outcome"] != "failure" or verdict["signature"] in signatures:
                continue
            try:
                stable, replays = confirm(evaluator, actions, verdict)
            except BudgetExhausted:
                events.append({"status": "unconfirmed-budget", "case_id": case_id})
                continue
            if not stable:
                events.append({"status": "unstable", "case_id": case_id,
                               "outcomes": [r["outcome"] for r in replays]})
                continue
            signatures.add(verdict["signature"])
            if parent_family:
                scheduler.record(parent_family, origin, 32, count_attempt=False,
                                 newly_productive=selection["reward"] == 0)
                corpus.credit(parent_family, 32)
            minimal, minimization = shrink(evaluator, actions, verdict["signature"])
            item = {"schema": "evofuzz/finding/1", "status": "confirmed-signature",
                    "binding_id": p.digest(binding), "actions": minimal, "original_actions": actions,
                    "signature": verdict["signature"], "kind": verdict["kind"], "id": verdict["id"],
                    "first_result": verdict, "replays": replay_receipts(replays),
                    "minimization": minimization}
            name = f"finding-{len(findings) + 1:04d}.json"
            p.write(out / name, item)
            findings.append(name)
            corpus.add(actions, verdict, generation, confirmed=True, event_id=descent["event_id"])
            if minimal != actions:
                corpus.add(minimal, generation=generation + 1, confirmed=True, event_id=f"minimize:{attempts}")
                lineage.write(p.canonical({"case_id": p.digest(minimal), "parents": [case_id],
                                          "event_id": f"minimize:{attempts}", "parent_events": [descent["event_id"]],
                                          "operator": "minimize", "generation": generation + 1,
                                          "status": "replayed-reduction"}) + "\n")
            recent_failures = (recent_failures + [{"kind": verdict["kind"], "id": verdict["id"],
                                                  "case_id": p.digest(minimal), "length": len(minimal)}])[-2:]
            if len(findings) == 128:
                status = "finding-limit"
                break
    with (out / "corpus.jsonl").open("w", encoding="utf-8") as stream:
        for actions in corpus.entries:
            stream.write(p.canonical(actions) + "\n")
    p.write(out / "archive.json", {"schema": "evofuzz/archive/1", "families": corpus.summaries(),
                                  "representatives": [
                                      {k: v for k, v in r.items() if k not in ("actions", "coverage")} |
                                      {"coverage_count": len(r["coverage"])} for r in corpus.records.values()]})
    p.write(out / "learning.json", {"schema": "evofuzz/learning/1", "operators": scheduler.stats,
                                   "exploration_percent": corpus.settings["exploration_percent"]})
    if evaluator.used < budget and status == "budget-complete":
        status = "attempt-limit"
    summary = {"schema": "evofuzz/run/1", "status": status, "seed": seed,
               "budget": budget, "evaluations": evaluator.used, "unique_cases": len(seen),
               "coverage": sorted(corpus.coverage)[:1024], "findings": findings,
               "events": events[:128], "proposer_calls": proposer_calls,
               "families_retained": len(corpus.summaries()),
               "inconclusive_candidates": any(e["status"] in ("unstable", "unconfirmed-budget")
                                                for e in events if "status" in e),
               "binding_id": p.digest(binding), "exhaustive": False}
    p.write(out / "summary.json", summary)
    return summary
