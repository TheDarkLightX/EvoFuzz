# State-space benchmarks

Three small stateful targets compare search strategies at equal evaluation budgets. They were
written for stateful search, and they measure these targets only.

| Target | Actions | Reachable labels | Planted defect |
|---|---:|---:|---|
| `lock.py` | 8 | 7 | Entering 3 1 4 1 5 lets an unauthorized `open` succeed; a wrong key restarts progress |
| `rooms.py` | 18 | 162 | Disarming fails when doors A and B are locked, C is open and D is closed: a four-way combination of easily covered component phases |
| `../examples/payments` | 25 (parameter domain) | 15 | Refund after payment pays out twice |

Each target can report `states` with `--states`, and every configuration passes `--bug`.

| Configuration | Meaning |
|---|---|
| `*-baseline.json` | The target reports no states; the frontier is off. This is the existing engine's behavior. |
| `*-frontier.json`, `../examples/payments/frontier.json` | The target reports states; the frontier is on with default settings. |
| `*-unlabelled.json` | Ablation: the frontier is on, but the target reports no states. |

Coverage labels, distance and families are identical across configurations. The lock reports
the highest stage reached, which gives mutation a gradient. The rooms target reports every
component phase, which gives none toward the failing combination.

## Reproduce

```sh
python3 benchmarks/run.py --tool . --budget 400 --seeds 10 --out bench.json \
  benchmarks/lock-baseline.json benchmarks/lock-frontier.json benchmarks/lock-unlabelled.json \
  benchmarks/rooms-baseline.json benchmarks/rooms-frontier.json benchmarks/rooms-unlabelled.json \
  examples/payments/target.json examples/payments/frontier.json
```

The figure of merit is the number of search evaluations before the first failing case,
read from each run's `cases.jsonl`. Confirmation and shrinking come afterwards. A run with
no failure within the budget is a miss. Write `--out` outside the repository; results are
run artifacts.

## Results

Seeds 0–9, 400 evaluations each, on one two-core Linux machine with Python 3.13. The baseline
rows ran on commit `3386b3d`, before this change. With the frontier off, the new engine
reproduced those runs exactly (first failure, evaluations and unique cases) for seeds 0–2 of
the lock and payments baselines.

| Target | Strategy | Found | Median evaluations to the first failure | Slowest found |
|---|---|---:|---:|---:|
| Lock | Baseline | 1/10 | 187 | 187 |
| Lock | Frontier | **10/10** | 35.5 | 128 |
| Lock | Frontier share, no labels | 0/10 | — | — |
| Rooms | Baseline | 1/10 | 140 | 140 |
| Rooms | Frontier | **5/10** | 148 | 293 |
| Rooms | Frontier share, no labels | 1/10 | 103 | 103 |
| Payments | Baseline | 10/10 | 15.5 | 50 |
| Payments | Frontier | 10/10 | **4** | 42 |

Every reduced witness had the shortest possible length: 6 actions for the lock, 5 for rooms
and 2 for payments. The ablation rows show that the gain comes from the reported labels, not
from spending more attempts on random walks.

The rooms target remains hard. It has 162 labels and 18 actions, so 2,916 transitions, and
the defect is one of them. Half the frontier runs did not reach it within 400 evaluations.

These are three targets, ten seeds and one machine, with no model in the loop. They show that
state labels can make the search far more efficient on targets like these. They do not
establish a general bug-finding advantage, and they carry no safety claim for any run
without findings.
