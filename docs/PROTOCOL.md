# Process and file protocols

All JSON is UTF-8. Duplicate keys, floating-point numbers, non-finite numbers,
integers beyond 64 bits and excessive nesting are refused. File JSON artifacts
are bounded to 1 MiB, nesting to 20 levels and nodes to 600000. Process stdout
and stderr have the stricter configured shared byte limit. Send one object and
exit. Logging belongs on stderr, within the shared output limit.

## Target configuration

```json
{
  "schema": "evofuzz/target/1",
  "objective": "Find a sequence that violates conservation.",
  "command": ["{python}", "target.py"],
  "oracle": ["{python}", "reference.py"],
  "bindings": ["target.py", "reference.py"],
  "vocabulary": [{"op":"pay"}, {"op":"refund"}],
  "seeds": [[], [{"op":"pay"}]],
  "limits": {"max_actions":32, "max_corpus":64},
  "proposer": ["provider-adapter", "--json-stdio"],
  "mutants": [{"id":"double-payment", "command":["{python}","target.py","--bug"]}]
}
```

`oracle`, `limits`, `proposer`, `mutants`, `domain` and `archive` are optional. This example's
`provider-adapter` is a placeholder for an executable you supply, not a bundled
command. Unknown fields are rejected. Bindings name files you want tracked;
declare transitive inputs when their changes matter.

Commands are argv arrays without shell expansion. Relative paths are resolved
in the target JSON's directory. `{python}` expands to the active interpreter.
Each process gets a fresh invocation; the harness must reset external state if
it uses persistent resources. Do not fuzz a live payment service by accident.

| Limit | Default | Allowed |
|---|---:|---:|
| max_actions | 32 | 1–128 |
| max_corpus | 64 | 1–128 |
| timeout_ms | 2000 | 10–60000 |
| output_bytes, stdout + stderr | 65536 | 1024–262144 |
| confirmations | 2 | 2–5 |
| shrink_budget, case evaluations | 100 | 0–1000 |
| proposer_interval, case evaluations | 50 | 1–10000 |
| proposer_timeout_ms | 30000 | 10–120000 |

The vocabulary contains 1–128 distinct JSON actions and at most 16 KiB of
canonical JSON. A case contains at most 32 KiB of canonical JSON. The retained
corpus holds at most `max_corpus` cases; the proposal queue holds at most 128.
Coverage memory holds at most 4096 labels. Search attempts are capped at eight
times the evaluation budget; exhausting attempts is reported explicitly.
At most 128 distinct failure signatures are retained per run.

## Case request

```json
{
  "schema":"evofuzz/case/1",
  "case_id":"sha256 of canonical actions",
  "actions":[{"op":"pay"},{"op":"refund"}]
}
```

Apply actions in order, checking properties after every step. `case_id` is an
identity, not authorization. Never deserialize executable model-generated code.

## Observation

```json
{
  "schema":"evofuzz/observation/1",
  "status":"fail",
  "observation":{"paid":1,"refunded":1},
  "coverage":["paid","refund-after-close"],
  "distance":0,
  "failure":{"id":"conservation","message":"One unit was spent twice."}
}
```

`status` is `pass`, `fail` or `invalid`. `observation` is required and contains
the deterministic semantic output to compare with a reference. It can include
the full step history; omit clocks and diagnostic counters. Coverage and
distance are optional. Distance is a nonnegative integer up to 1000000;
smaller is more interesting. Coverage has at most 128 labels per response.

A failure requires a stable `failure.id`. Nonfailure observations must omit
`failure`. For differential checking, statuses and observations must match.
A reported target property failure has priority over differential mismatch.
Failures are grouped by the hash of `(kind, id)`; grouping is deliberately
coarse and may merge different root causes with the same oracle ID.

An oracle transport failure stops comparison. A nonzero **target** exit is a
crash candidate, separately labelled `process-exit`; this can also represent a
harness defect. Timeout, excessive output and malformed JSON are execution
errors, not automatically declared program vulnerabilities.

## Model proposals

`prompt` emits `evofuzz/proposal-request/1`: objective, target fingerprint,
vocabulary, bounds, operators, corpus examples and available feedback. Its
`request_id` is the hash of the packet before that field is added.

```json
{
  "schema":"evofuzz/proposal/1",
  "request_id":"exact request_id from the packet",
  "hypothesis":"A refund after successful payment may spend the unit twice.",
  "cases":[[{"op":"pay"},{"op":"refund"}]],
  "weights":{"duplicate":3,"insert":5}
}
```

There may be up to 16 proposed cases. Cases must match the declared prototypes,
parameter domains and required setup. Optional weights are integers 1–100 for
operators named in the request: `insert`, `replace`, `delete`, `duplicate`,
`swap`, `splice`, `random`, and, where configured, `parameter`, `rebind`, `block`.
Optional `family_weights` maps only family IDs named in the exact request to
positive integer weights 1–100. Unspecified weights retain their prior values.
Every operator retains positive weight. Hypotheses are advisory text;
they are never executed or accepted as failure evidence.

Offline proposals match the initial `prompt` packet for exactly that target
and source state. Adaptive command proposals match their current packet.
Stale proposals, unknown fields and attempts to supply commands/oracles are
rejected. Invalid adaptive proposals are logged and search continues.

## Domain-aware evolution (0.2)

`domain.parameters` declares scalar enum fields (`{"values":["A","B"]}`) or
integer fields (`{"min":0,"max":100}`). There are at most 16 parameter fields,
64 enum values per field and integer widths up to 1000000000. Integer endpoints
are signed 64-bit. Enum values are null, Boolean, integer or strings up to 128
characters. Boolean true and integer 1 are distinct values.

Actions must match a vocabulary prototype's exact keys and nonparameter
constants. Only fields present in that prototype may vary. `op` cannot be a
parameter. `identity_fields` lists at most eight enum fields for correlated or
individual rebinding. `blocks` contains at most 16 uniquely named sequences of
1–16 valid actions. A selected block is inserted whole only when it fits.
`setup` is an optional fixed prefix of at most 16 actions. It counts toward
`max_actions` and is enforced on seeds, proposals and mutations. The complete
domain declaration is limited to 16 KiB. No Cartesian domain is materialized.

`archive.features` lists 1–4 target observation feature names, default
`["family"]`. An optional observation `features` object holds at most 16 bounded
scalar descriptors (strings up to 128 characters). Features guide search; they
are neither oracle verdicts nor checked semantic equivalence claims. Missing
features are marked explicitly. When all selected features are absent, the
archive uses a labelled structural pattern/length descriptor.

`archive.per_family` is 1–4, bounded by `max_corpus`, default min(2,max_corpus).
Within a family, retain a quality champion and, if slots permit, representatives
whose action/adjacent-action token sets differ most from those retained. When
full, reclaim extra representatives before removing an entire family. Capacity
can still force the loss of families; the archive does not preserve all niches.

Quality prioritizes confirmed failures, lower distance, coverage and shorter
sequences. Useful offspring earn bounded novelty/retention rewards. A newly
replayed failure adds a separate reward without counting another mutation
attempt. The scheduler learns per-family operator reward rates using integer
weights. Parent-family selection uses selection counts and offspring rewards.
At most 256 named learning contexts plus one overflow context are retained.

`archive.exploration_percent` is 1–100, default 20. After initial seeds, each
attempt has that probability of uniform family/representative/operator
exploration, independent of learned/model weights. A model proposal queue
cannot consume these exploration attempts. This is a probability per attempt,
not a promise of an exact fraction in a short run. Transport failures and
unconfirmed findings are not rewarded as confirmed bugs.

New artifacts: `archive.json` stores family and representative metadata,
`learning.json` stores scheduling statistics, and `lineage.jsonl` records every
search attempt, including duplicates, plus completed reductions. Case hashes identify content; distinct event IDs
identify derivations, so a sequence can reappear without a cyclic ancestry
claim. Splicing names both parents; random generation and externally supplied
cases do not invent genetic parents. Confirmation receipts and minimization
summaries remain in findings; not every intermediate shrink trial is logged.

## Replay and mutation testing

`replay TARGET --run RUN` checks fingerprints and repeats a finding. Optional
`--finding finding-0002.json` selects another. `minimize` performs an additional
bounded shrink after replay; neither command alters the original evidence.
`--out FILE` saves their result in a new file. Replay receipts contain outcomes,
failure signatures and hashes of full execution results; the first full result
is also stored. These are unsigned local records, not attestations.

`mutation-test` reads JSONL containing one action array per line. It requires
baseline passes, then compares each variant with the baseline. Results are
`killed`, `survived`, `unstable` or `error`. It does not judge whether a changed
behavior was actually intended to be a defect.

## Exit codes

| Command | 0 | 1 | 2 |
|---|---|---|---|
| run | bounded search completed, no confirmed findings | confirmed findings | execution/configuration error or inconclusive candidate |
| prompt | request written | — | invalid configuration/output |
| replay / minimize | failure signature reproduced | — | mismatch, drift or execution error |
| mutation-test | all supplied variants killed | at least one survived | baseline failure, unstable variant or execution error |

Read `summary.json` and its events as well as the exit code. In particular,
an unconfirmed candidate at budget exhaustion is not a confirmed finding and
produces exit 2. A run can contain confirmed findings and still exit 2 if other
candidates remained inconclusive or execution failed.
