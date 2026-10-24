# EvoFuzz design

EvoFuzz is a standalone, LLM-steerable evolutionary fuzzer for bounded action
sequences. The requirements below define the implementation; a run
finds counterexamples, not a proof that no counterexamples exist.

## Search and authority

1. A user-owned target file fixes the objective, action vocabulary, seed cases,
   process commands, declared input files, and execution/search limits.
2. Each case is a list of declared actions. A seeded PRNG applies insertion,
   replacement, deletion, duplication, swapping, splicing and random generation.
   Optional typed parameter domains, identity rebinding, named blocks and fixed
   setup prefixes support domain-specific sequences.
3. A bounded archive retains behavioral families and structurally different
   representatives. Online scheduling learns useful parent-family/operator
   combinations from coverage novelty, distance and confirmed failures, with
   a configured probability of uniform exploration. These signals guide search;
   they do not establish a bug. Family definitions and bounds are in
   [Domain-aware evolution](docs/EVOLVABILITY.md).
4. Periodic LLM proposals may supply domain-valid cases and mutation/family weights.
   Proposals must name the exact request hash. They cannot edit commands,
   objectives, oracles, limits, file bindings or verdicts.
5. The target checks its properties after every action. An optional independent
   reference process enables differential checking of normalized observations.
6. A property failure, observation mismatch or target process exit is a finding
   candidate. Repeated execution must reproduce its failure signature before
   confirmation. A timeout, invalid input, malformed response, unavailable
   oracle, source drift or inconsistent result is not a confirmed semantic bug.
7. Delta debugging removes action chunks, retaining only candidates that repeat
   the same failure. The result is locally deletion-minimal only if its bounded
   minimization finishes; global minimality is not claimed.

The LLM is an untrusted proposer. Target oracles are user-supplied trusted code.
Their correctness and completeness are outside the fuzzer's guarantees.

## Interfaces

The implementation uses Python 3.11+ and the standard library. Targets and
proposers are explicit argv arrays, executed without a shell. A target process
receives one JSON request on stdin, returns one JSON observation on stdout,
and exits. Fresh processes reset target state between cases.

`{python}` expands to the current Python interpreter. Other relative arguments
are interpreted in the target file's directory. The target protocol works with
any language that can read and write JSON.

The optional proposer has the same bounded process interface. It runs only
when the user supplies `--enable-proposer`. Offline request/proposal files let
an agent steer search without a model-specific SDK or API key in the fuzzer.

## Evidence

Each run records its validated configuration, original target file, resolved
commands, executable hashes, declared file hashes, PRNG seed, attempted cases,
feedback, proposals, bounded archive, mutation lineage, learning statistics,
finding candidates and replay results. Duplicate attempts are visible in the
lineage log; descendants need not have distinct behavior. Fresh random restarts
and model-supplied cases have no inferred genetic parents.
Input fingerprints are checked before and after execution. This detects
persistent changes; it does not defeat a concurrent edit-and-restore race or
prove a complete dependency closure. Declared fingerprints are not signed
attestations or proof that those bytes were executed. Replay refuses changed
declared bindings and configuration.

JSON rejects duplicate keys, non-finite numbers, floats and excessive depth.
Case lengths, vocabulary size, corpus size, number of executions, response
bytes, per-process time and minimization work have explicit limits. Time and
output violations stop the process. POSIX process groups include ordinary
children; this is not a sandbox, and a malicious target can escape a group.
Commands run with the user's filesystem and network permissions. The fuzzer
does not provide OS memory, CPU or filesystem isolation.

## Mutation testing

The user may provide explicit mutant commands representing faulty program
variants. The mutation-test command first requires the baseline to pass every
case in a supplied corpus. It then evaluates each variant against that same
corpus and the baseline's observations. A detected difference is a killed
mutant, with a replayed witness. An execution/transport failure is an error;
a surviving mutant means not detected by this corpus. The tool does not edit
source code or assume that every supplied mutant is semantically incorrect.

## Definition of done

- Standalone package and CLI: run, prompt, replay, minimize, mutation-test.
- Offline and opt-in command-backed LLM steering, with exact request binding.
- Repeatable domain-aware mutation, family retention and learned scheduling.
- Property and differential oracles, replay confirmation and bounded shrinking.
- Process deadlines/output bounds, malformed-input and source-drift controls.
- A correct escrow target, deliberately faulty variants, and an independent
  executable reference demonstrating multi-step failures and mutation kills.
- Tests for search, semantic mismatch, proposal tampering, false positives,
  replay drift, minimization, timeout/output limits and mutation-test errors.
- Public README, protocol documentation, research references, CI, an agent
  usage skill, and a portable standalone repository.

No live service scans, external model charges, automatic repairs, release tag,
performance superiority or formal correctness claim are in scope.

## Research basis

- [Fuzz4All](https://arxiv.org/abs/2308.04748): LLM input generation and mutation,
  with iterative feedback. EvoFuzz's first implementation is independent.
- [Systematic Assessment of Fuzzers using Mutation Analysis](https://www.usenix.org/conference/usenixsecurity23/presentation/gorz):
  evaluate tests against injected faults rather than coverage alone.
- [RESTler](https://www.microsoft.com/en-us/research/publication/restler-stateful-rest-api-fuzzing/):
  stateful request sequences as a fuzzing surface. EvoFuzz's finite action
  vocabulary is simpler than a REST dependency inference system.
