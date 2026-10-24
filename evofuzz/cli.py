"""Command-line workflows for search, agent steering and reproducible evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__, protocol as p
from .config import load
from .engine import Evaluator, confirm, replay_receipts, request, run, shrink


def replay(config, directory, name="finding-0001.json", minimize=False):
    directory = Path(directory)
    binding = p.read(directory / "bindings.json")
    p.require(config.fingerprint() == binding, "target/tool/declared inputs changed; replay refused")
    p.require(Path(name).name == name, "finding must be a basename within the run")
    finding = p.read(directory / name)
    p.require(finding.get("schema") == "evofuzz/finding/1", "wrong finding schema")
    p.require(finding["binding_id"] == p.digest(binding), "finding binding mismatch")
    actions = p.case(finding["actions"], config.vocabulary, config.limits["max_actions"])
    evaluator = Evaluator(config, binding, config.limits["confirmations"] + config.limits["shrink_budget"])
    stable, results = confirm(evaluator, actions)
    matched = stable and results[0].get("signature") == finding["signature"]
    report = {"schema": "evofuzz/replay/1", "matched": matched, "actions": actions,
              "signature": finding["signature"], "results": replay_receipts(results),
              "first_result": results[0], "binding_id": p.digest(binding)}
    if matched and minimize:
        actions, detail = shrink(evaluator, actions, finding["signature"])
        report.update(actions=actions, minimization=detail)
    return report


def read_cases(path, config):
    cases = []
    total = 0
    with Path(path).open("rb") as stream:
        while line := stream.readline(65_538):
            total += len(line)
            p.require(len(line) <= 65_537 and total <= 16_777_216, "case corpus byte limit")
            if not line.strip():
                continue
            cases.append(p.case(p.loads(line), config.vocabulary, config.limits["max_actions"]))
            p.require(len(cases) <= 1024, "case corpus count limit")
    p.require(bool(cases), "empty case corpus")
    return cases


def mutation_test(config, cases):
    binding = config.fingerprint()
    mutants = config.data.get("mutants", [])
    p.require(bool(mutants), "no mutants configured")
    evaluator = Evaluator(config, binding, len(cases) * (1 + len(mutants)) * config.limits["confirmations"])
    for index, actions in enumerate(cases):
        result = evaluator.evaluate(actions)
        if result["outcome"] != "pass":
            return {"schema": "evofuzz/mutation-test/1", "status": "baseline-failed",
                    "case_index": index, "result": result, "mutants": []}
    reports = []
    for mutant in mutants:
        entry = {"id": mutant["id"], "status": "survived"}
        for index, actions in enumerate(cases):
            result = evaluator.evaluate(actions, "mutant:" + mutant["id"], "target")
            if result["outcome"] == "error":
                entry.update(status="error", case_index=index, reason=result["reason"])
                break
            if result["outcome"] == "failure":
                stable, repeated = confirm(evaluator, actions, result, "mutant:" + mutant["id"], "target")
                entry.update(status="killed" if stable else "unstable", case_index=index,
                             actions=actions, signature=result["signature"],
                             repeated_outcomes=[r["outcome"] for r in repeated])
                break
        reports.append(entry)
    return {"schema": "evofuzz/mutation-test/1", "status": "complete", "mutants": reports,
            "evaluations": evaluator.used, "binding_id": p.digest(binding),
            "corpus_id": p.digest([p.digest(c) for c in cases]), "case_count": len(cases)}


def parser():
    result = argparse.ArgumentParser(description="LLM-steerable evolutionary fuzzing with replayable counterexamples.")
    result.add_argument("--version", action="version", version="evofuzz " + __version__)
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("run", "prompt", "replay", "minimize", "mutation-test"):
        item = sub.add_parser(name)
        item.add_argument("target", type=Path, help="User-owned evofuzz/target/1 JSON file")
        if name == "run":
            item.add_argument("--out", type=Path, required=True, help="New run directory")
            item.add_argument("--seed", type=int, default=0)
            item.add_argument("--budget", type=int, default=200, help="Case evaluations, including confirmation and shrinking")
            item.add_argument("--proposal", type=Path, help="Offline proposal matching 'prompt' for this target")
            item.add_argument("--enable-proposer", action="store_true", help="Execute the configured proposer command periodically")
        elif name == "prompt":
            item.add_argument("--out", type=Path, required=True)
        elif name in ("replay", "minimize"):
            item.add_argument("--run", type=Path, required=True)
            item.add_argument("--finding", default="finding-0001.json")
            item.add_argument("--out", type=Path)
        else:
            item.add_argument("--cases", type=Path, required=True, help="JSONL: one action array per line")
            item.add_argument("--out", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = load(args.target)
        if args.command == "run":
            result = run(config, args.out, args.seed, args.budget,
                         p.read(args.proposal) if args.proposal else None, args.enable_proposer)
            code = 2 if result["status"] == "stopped-on-execution-error" or result["inconclusive_candidates"] else 1 if result["findings"] else 0
        elif args.command == "prompt":
            p.require(not args.out.exists(), "output file exists")
            result = request(config, config.fingerprint())
            p.write(args.out, result)
            code = 0
        elif args.command in ("replay", "minimize"):
            result = replay(config, args.run, args.finding, args.command == "minimize")
            if args.out:
                p.require(not args.out.exists(), "output file exists")
                p.write(args.out, result)
            code = 0 if result["matched"] else 2
        else:
            p.require(not args.out.exists(), "output file exists")
            result = mutation_test(config, read_cases(args.cases, config))
            p.write(args.out, result)
            code = 2 if result["status"] != "complete" or any(
                m["status"] in ("error", "unstable") for m in result["mutants"]) else 1 if any(
                m["status"] == "survived" for m in result["mutants"]) else 0
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
