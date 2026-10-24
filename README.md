# EvoFuzz

**Steer evolutionary fuzzing toward the failure you care about.**

Give EvoFuzz a stateful target, an action vocabulary and a concrete question:

> Can a retry sequence pay and refund the same deposit?

EvoFuzz mutates action sequences, executes them and retains useful cases across
different behavioral families. It learns which mutations produce useful
offspring in each family while preserving uniform exploration.
An LLM can propose sequences and steer mutation weights using the observed
feedback. Your executable properties and reference models decide whether a
case fails. Reproducible findings are saved and reduced to shorter witnesses.

```text
objective + seeds → mutate → execute → check → retain → repeat
                        ↑                       │
                   LLM proposals ← feedback ───┘
```

This implementation focuses on structured, stateful testing. It has no runtime
dependencies beyond Python 3.11+. Targets can be written in any language that
can exchange JSON with a process.

## Try it

From the checkout, without installing anything:

```sh
python3 -m evofuzz run examples/escrow/buggy.json --out runs/escrow --seed 7 --budget 100
python3 -m evofuzz replay examples/escrow/buggy.json --run runs/escrow
```

The first command should discover the deliberately planted `pay → refund`
defect and exit **1** to signal a finding. The second command replays its
failure signature. Each `--out` run directory must be new.

The correct implementation can be tested separately:

```sh
python3 -m evofuzz run examples/escrow/correct.json --out runs/correct --seed 7 --budget 100
```

A run without findings reports only what that bounded search observed. It is
not an exhaustive safety check.

For an installed CLI:

```sh
python3 -m pip install .
evofuzz --help
```

On systems where Python is named `python`, use that command instead.

## What steers the search?

- **Fast mutations:** insert, replace, delete, duplicate, swap, splice and
  generate fresh action sequences, using a repeatable PRNG seed.
- **Domain-aware mutations:** vary declared parameter values, rebind request
  identities and insert named action blocks while preserving required setup.
- **Behavioral families:** retain quality and structural-diversity representatives
  of target-reported families instead of replacing cases solely by age.
- **Online learning:** measured offspring productivity steers parent and operator
  selection; coverage and distance remain advisory search signals.
- **LLM proposals:** a model suggests vocabulary-valid cases and mutation
  and family weights in response to domain, archive and feedback packets.
- **Oracles:** executable properties and optional differential references
  identify failures. Coverage and distance alone cannot declare a bug.

Use failures such as conservation violations, unauthorized transitions,
non-atomic rejection, duplicate effects or divergent replay. The harness must
check them after **every action**, including intermediate steps.

## From one seed to several families

The payment-domain example begins with `[pay(A), pay(A)]`. Its declared domain
adds identities A/B, owner/outsider actors, amounts 0–2, refunds and restarts:

```sh
python3 -m evofuzz run examples/payments/target.json --out runs/families --seed 7 --budget 200
```

Inspect `archive.json` for retained families, `lineage.jsonl` for parent/child
events and `learning.json` for mutation attempts and rewards. The target labels
replay, identity, authorization, reversal and recovery families. These labels
describe explored behaviors; a label alone does not establish a bug.

Each descendant is a concrete test sequence. Several descendants can explore
the same family or produce the same sequence; duplicates are skipped and
logged. New operations and parameter values must be declared by the user.
See the [evolvability design](docs/EVOLVABILITY.md) for the retention, learning
and domain contract.

## Connect an agent or LLM

Create a request:

```sh
python3 -m evofuzz prompt examples/escrow/buggy.json --out request.json
```

Give `request.json` to your agent. It returns a proposal with the exact request
ID, action sequences and optional mutation weights. Then run:

```sh
python3 -m evofuzz run examples/escrow/buggy.json --out runs/guided --proposal proposal.json --budget 100
```

For an adaptive campaign, configure a `proposer` argv array in the target JSON
and pass `--enable-proposer`. EvoFuzz periodically sends that command a new
request on stdin and reads its JSON proposal from stdout. This works through a
provider adapter or a local model; EvoFuzz does not require a particular model,
SDK or API key. Proposer commands may incur charges or transmit data according
to their own configuration. They are never launched without the opt-in flag.

`examples/scripted_proposer.py` and `examples/escrow/guided-demo.json`
demonstrate that interface. **The scripted proposer is not an LLM.** Its tests
establish protocol behavior, not a benefit from model intelligence. An agent
usage guide is available at [skills/evofuzz/SKILL.md](skills/evofuzz/SKILL.md).

## Test your tests

Mutation testing runs explicitly supplied faulty program variants against a
corpus that first passes on the baseline:

```sh
python3 -m evofuzz mutation-test examples/escrow/correct.json --cases examples/escrow/cases.jsonl --out mutation-results.json
```

The example corpus catches both a refund-after-payment defect and a missing
authorization check. A surviving mutant is simply one this corpus did not
detect. Timeouts and unavailable oracles are reported as errors.

Input mutation is fuzzing; program mutation evaluates the strength of your
tests. EvoFuzz supports both without editing your source files automatically.

## Evidence and limits

A run saves attempted cases, feedback, proposals, a retained corpus, declared
input fingerprints, replay results and reduced findings. `--budget` covers
case evaluations, including confirmation and shrinking. A reference oracle
adds a second process per evaluation; proposer calls have their own deadline.

Confirmed findings reproduce the same failure **signature** across the
configured number of executions. This is evidence of reproducibility under
those executions, not a proof of determinism or oracle correctness. A reduced
case is only deletion-minimal when its report says minimization completed.

Targets and proposer commands run with your permissions. **This is not a
sandbox.** Use an isolated environment for untrusted programs. EvoFuzz bounds
process time and captured output; it does not impose OS memory, CPU or
filesystem isolation. POSIX process-group cleanup covers ordinary descendants.
On Windows only the direct process is terminated; use external job/container
isolation when child cleanup matters.

Fingerprints cover the declared files, executables, target configuration and
EvoFuzz source. Replay with a changed tool version is refused; preserve the
matching executable/source for older runs. Fingerprints do not establish a
complete dependency closure or defeat
an input that is edited and restored during execution. Environment variables,
shared libraries and remote services remain outside those fingerprints.
Run artifacts can contain sensitive test data; they are Git-ignored by default.

See the [protocol](docs/PROTOCOL.md), [design](DESIGN.md) and
[validation record](VALIDATION.md). GPU acceleration, symbolic path solving,
automatic source mutation and formal safety proofs are outside version 0.2.

## Development

```sh
python3 -m unittest discover -v
```

Optional linting: `ruff check evofuzz examples tests`. CI also runs the examples
on Linux, macOS and Windows. Hosted results are separate from local validation.

EvoFuzz uses the repository's existing [MIT license](LICENSE).
