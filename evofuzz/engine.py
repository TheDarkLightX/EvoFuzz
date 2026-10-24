"""Deterministic evolutionary search; target-owned oracles establish failures."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import random

from . import protocol as p
from .config import Config
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
        actions = p.case(actions, cfg.vocabulary, cfg.limits["max_actions"])
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


def mutate(rng, actions, vocabulary, max_actions, corpus, weights):
    result = copy.deepcopy(actions)
    op = rng.choices(p.OPERATORS, weights=[weights[x] for x in p.OPERATORS], k=1)[0]
    def action():
        return copy.deepcopy(rng.choice(vocabulary))
    if op == "random":
        result = [action() for _ in range(rng.randrange(max_actions + 1))]
    elif op == "insert" or not result:
        result.insert(rng.randrange(len(result) + 1), action())
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
        donor = rng.choice(corpus)
        result = result[:rng.randrange(len(result) + 1)] + copy.deepcopy(donor[rng.randrange(len(donor) + 1):])
    return result[:max_actions], op


class Corpus:
    def __init__(self, seeds, cap):
        self.entries = []
        self.coverage = set()
        self.distance = 1_000_001
        self.cap = cap
        for actions in seeds:
            self.add(actions)

    def add(self, actions):
        if actions not in self.entries:
            self.entries.append(copy.deepcopy(actions))
            if len(self.entries) > self.cap:
                self.entries.pop(0)

    def observe(self, actions, result):
        value = result.get("target", {}).get("value", {})
        coverage = set(value.get("coverage", []))
        distance = value.get("distance", 1_000_000)
        interesting = bool(coverage - self.coverage) or distance < self.distance
        self.coverage.update(sorted(coverage - self.coverage)[:max(0, 4096 - len(self.coverage))])
        self.distance = min(self.distance, distance)
        if interesting:
            self.add(actions)


def request(config, binding, corpus=None, feedback=None):
    packet = {"schema": "evofuzz/proposal-request/1", "objective": config.data["objective"],
              "target_id": p.digest(binding), "vocabulary": config.vocabulary,
              "max_actions": config.limits["max_actions"], "operators": list(p.OPERATORS),
              "corpus": [], "feedback": feedback or {},
              "instructions": "Return evofuzz/proposal/1 with this request_id, cases (arrays of vocabulary actions), optional weights and hypothesis. Do not change the target, oracle, objective or bounds."}
    for actions in (corpus or config.data["seeds"])[:4]:
        candidate = packet | {"corpus": packet["corpus"] + [actions]}
        try:
            if len(p.canonical(candidate)) > 65_536:
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
    corpus = Corpus(config.data["seeds"], config.limits["max_corpus"])
    queue = copy.deepcopy(config.data["seeds"])
    initial_request = request(config, binding)
    p.write(out / "request.json", initial_request)
    weights = dict.fromkeys(p.OPERATORS, 1)
    events, findings, seen = [], [], set()
    signatures = set()
    recent_failures = []
    if proposals is not None:
        cases, changes = p.proposal(proposals, initial_request, config.vocabulary, config.limits["max_actions"])
        queue = (queue + cases)[:128]
        weights.update(changes)
        p.write(out / "offline-proposal.json", proposals)
    attempts, proposer_calls, next_proposal = 0, 0, config.limits["proposer_interval"]
    status = "budget-complete"
    with (out / "cases.jsonl").open("w", encoding="utf-8") as log:
        while evaluator.used < budget and attempts < budget * 8:
            if enable_proposer and evaluator.used >= next_proposal:
                packet = request(config, binding, corpus.entries, {"evaluations": evaluator.used,
                                 "coverage": sorted(corpus.coverage)[:128], "findings": len(findings),
                                 "recent_failures": recent_failures})
                proposer_calls += 1
                result = execute(config.commands["proposer"], (p.canonical(packet) + "\n").encode(),
                                 config.root, config.limits["proposer_timeout_ms"], config.limits["output_bytes"])
                record = {"request": packet, "transport": result.status}
                try:
                    p.require(result.status == "completed" and result.code == 0, "proposer execution failed")
                    proposed = p.loads(result.stdout)
                    cases, changes = p.proposal(proposed, packet, config.vocabulary, config.limits["max_actions"])
                    queue = (queue + cases)[:128]
                    weights.update(changes)
                    record.update(status="accepted", proposal=proposed)
                except ValueError as exc:
                    record.update(status="rejected", reason=str(exc))
                p.write(out / f"proposal-{proposer_calls:04d}.json", record)
                next_proposal = evaluator.used + config.limits["proposer_interval"]
            attempts += 1
            if queue:
                actions, origin = queue.pop(0), "supplied"
            else:
                actions, origin = mutate(rng, rng.choice(corpus.entries), config.vocabulary,
                                         config.limits["max_actions"], corpus.entries, weights)
            case_id = p.digest(actions)
            if case_id in seen:
                continue
            seen.add(case_id)
            verdict = evaluator.evaluate(actions)
            log.write(p.canonical({"actions": actions, "case_id": case_id, "origin": origin, "result": verdict}) + "\n")
            log.flush()
            corpus.observe(actions, verdict)
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
            minimal, minimization = shrink(evaluator, actions, verdict["signature"])
            item = {"schema": "evofuzz/finding/1", "status": "confirmed-signature",
                    "binding_id": p.digest(binding), "actions": minimal, "original_actions": actions,
                    "signature": verdict["signature"], "kind": verdict["kind"], "id": verdict["id"],
                    "first_result": verdict, "replays": replay_receipts(replays),
                    "minimization": minimization}
            name = f"finding-{len(findings) + 1:04d}.json"
            p.write(out / name, item)
            findings.append(name)
            corpus.add(minimal)
            recent_failures = (recent_failures + [{"kind": verdict["kind"], "id": verdict["id"],
                                                  "case_id": p.digest(minimal), "length": len(minimal)}])[-2:]
            if len(findings) == 128:
                status = "finding-limit"
                break
    with (out / "corpus.jsonl").open("w", encoding="utf-8") as stream:
        for actions in corpus.entries:
            stream.write(p.canonical(actions) + "\n")
    if evaluator.used < budget and status == "budget-complete":
        status = "attempt-limit"
    summary = {"schema": "evofuzz/run/1", "status": status, "seed": seed,
               "budget": budget, "evaluations": evaluator.used, "unique_cases": len(seen),
               "coverage": sorted(corpus.coverage)[:1024], "findings": findings,
               "events": events[:128], "proposer_calls": proposer_calls,
               "inconclusive_candidates": any(e["status"] in ("unstable", "unconfirmed-budget")
                                                for e in events if "status" in e),
               "binding_id": p.digest(binding), "exhaustive": False}
    p.write(out / "summary.json", summary)
    return summary
