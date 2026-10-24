---
name: evofuzz
description: Search for reproducible multi-step program failures with EvoFuzz; use for stateful action sequences, retry/replay defects, executable invariants, differential oracles, and testing whether supplied faulty variants are detected.
---

# EvoFuzz: steer, execute, replay

Run commands with EvoFuzz installed, or from its repository checkout.

Use when a bug may require ordered actions, when structured syntax gates the
interesting behavior, or when you want to test an oracle against planted faults.
Use a proof/model checker when the goal is to establish absence over a complete
domain; a fuzz campaign alone cannot do that.

## Before search

1. State a concrete disaster: duplicated payment, unauthorized acceptance,
   changed state on rejection, divergence from reference, or failed replay.
2. Identify the real implementation boundary. Write a target harness that
   consumes `evofuzz/case/1`, applies the sequence and checks properties after
   every action. Supply an independent reference when practical.
3. Review the user-owned target JSON, commands, bindings, vocabulary and bounds.
   Targets execute with user permissions. Choose an isolated test environment;
   never introduce live service traffic or credentials merely to fuzz.
4. Establish that the baseline and a deliberately faulty variant produce the
   expected outcomes before trusting campaign findings.

## Run and steer

```sh
python3 -m evofuzz run TARGET.json --out runs/baseline --seed 7 --budget 200
python3 -m evofuzz prompt TARGET.json --out request.json
```

Read the complete request. Propose actions that can cross a named semantic
barrier: repeat an identifier, retry after partial success, interleave two
actors, omit authority, cancel after completion, or hit declared boundaries.
Stay within the vocabulary. If the vocabulary cannot express the hypothesis,
report the missing capability; do not silently weaken the question.

Write `evofuzz/proposal/1` with the exact request ID, up to 16 action arrays and
optional mutation weights. Do not add commands, oracle changes or verdicts.

```sh
python3 -m evofuzz run TARGET.json --out runs/steered --proposal proposal.json --seed 7 --budget 200
```

For configured adaptive proposer commands, add `--enable-proposer` only with
authorization for that command and its data/cost implications. The bundled
scripted proposer tests the interface; it does not measure LLM effectiveness.

## Verify and learn

```sh
python3 -m evofuzz replay TARGET.json --run runs/steered
python3 -m evofuzz minimize TARGET.json --run runs/steered --out reduced.json
python3 -m evofuzz mutation-test TARGET.json --cases cases.jsonl --out mutations.json
```

Inspect the property ID, every step of the witness, target and reference
observations, source fingerprints, repeat results and minimization status.
Distinguish a target defect from an oracle/harness defect. Timeouts, source
drift, malformed output and unavailable references stay errors or inconclusive.

For repairs, keep the failing witness as a regression, rerun it against the
unchanged oracle and then use a fresh campaign. Do not modify requirements to
make a candidate pass. Report the actual revision, bounds and attempts.

To evaluate model steering, freeze tasks, model, budgets and oracles; compare
with the same seeded unguided engine on held-out tasks. Count reproducible bugs,
false positives, executions, model cost and total time. A prompted worked
example is not natural workflow discovery or a benchmark win.
