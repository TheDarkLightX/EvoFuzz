"""Compare search strategies at equal evaluation budgets on the benchmark targets.

    python3 benchmarks/run.py --tool . --budget 400 --seeds 10 --out results.json lock-frontier.json ...

Each run is a real `python -m evofuzz run` from the checkout given by --tool. The figure of
merit is the number of search evaluations before the first case that fails, read from the
run's cases.jsonl; confirmation and shrinking happen afterwards. A run without a failure
within the budget counts as a miss. This measures these targets only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile


def one(tool, config, seed, budget):
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "run"
        proc = subprocess.run([sys.executable, "-m", "evofuzz", "run", str(config), "--out", str(out),
                               "--seed", str(seed), "--budget", str(budget)],
                              cwd=tool, capture_output=True, text=True, timeout=3600)
        summary = json.loads((out / "summary.json").read_text())
        first = None
        with (out / "cases.jsonl").open() as log:
            for index, line in enumerate(log, 1):
                if json.loads(line)["result"]["outcome"] == "failure":
                    first = index
                    break
        witness = None
        if summary["findings"]:
            finding = json.loads((out / summary["findings"][0]).read_text())
            witness = dict(length=len(finding["actions"]),
                           deletion_minimal=finding["minimization"]["deletion_minimal"])
        graph = summary.get("state_graph")
        return dict(seed=seed, exit=proc.returncode, status=summary["status"], first_failure=first,
                    evaluations=summary["evaluations"], unique_cases=summary["unique_cases"], witness=witness,
                    states=graph and graph.get("states"), closed_depth=graph and graph.get("closed_depth"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True)
    ap.add_argument("--budget", type=int, default=400)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", required=True)
    ap.add_argument("configs", nargs="+")
    a = ap.parse_args()
    tool = Path(a.tool).resolve()
    jobs = [(Path(c).resolve(), s) for c in a.configs for s in range(a.seeds)]
    with ThreadPoolExecutor(a.jobs) as pool:
        runs = list(pool.map(lambda job: (job[0], one(tool, job[0], job[1], a.budget)), jobs))
    report = {}
    for config in dict.fromkeys(c for c, _ in jobs):
        rows = [r for c, r in runs if c == config]
        hits = sorted(r["first_failure"] for r in rows if r["first_failure"])
        report[config.name] = dict(budget=a.budget, seeds=a.seeds, found=len(hits),
                                   median_evaluations_to_failure=statistics.median(hits) if hits else None,
                                   worst_found=max(hits) if hits else None, runs=rows)
        print(f"{config.name:28} found {len(hits)}/{a.seeds}  median {report[config.name]['median_evaluations_to_failure']}"
              f"  worst {report[config.name]['worst_found']}")
    Path(a.out).write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
