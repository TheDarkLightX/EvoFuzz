# Validation scope

This record describes version 0.2.0's local checks. It is not a
formal proof, external audit or model-guidance benchmark.

The suite exercises the real subprocess boundary, complete example workflows
and malformed/adversarial protocol cases. The deliberately faulty escrow
variants are demonstration defects, not newly discovered product vulnerabilities.

Local qualification passed on Linux with Python 3.12.3:

| Check | Result |
|---|---|
| Unit/integration suite | 49 passed |
| Lint and Python compilation | Passed |
| Unguided buggy-escrow campaign | Found the planted conservation defect |
| Reduced witness | Authorized pay, then authorized refund |
| Replay and further minimization | Passed; two-action witness retained |
| Correct-escrow campaign | No findings in 40 case evaluations |
| Mutation testing | Both supplied faulty variants killed |
| Offline proposals and adaptive command interface | Passed |
| Domain-aware payment campaign | Six families retained, including all five named behavior families |
| Parameter/identity/block mutations and fixed setup | Passed |
| Family retention and distinct equivalent-behavior representatives | Passed |
| Learned parent/operator selection and independent exploration | Passed |
| Parent-event lineage, splicing and duplicate records | Passed |
| Installed wheel outside checkout | Version, search and replay passed |
| Documentation links, agent skill format and public-source scan | Passed |

The escrow campaign used seed 7 and an 80-evaluation budget for the buggy target.
These counts include confirmation and minimization, not just search proposals.
The absence of findings in the correct target's bounded campaign is not a
proof of safety. The two planted mutants do not establish general mutation
coverage. Model-guidance effectiveness remains unmeasured.

The payment-domain campaign started only from `[pay(A), pay(A)]`, with the
declared parameter domains and action blocks. With seed 7 and 200 evaluations,
it retained authorization, identity, recovery, replay, reversal and exploration
descriptors. It found and replayed the planted conservation defect. The family
labels come from this harness's explicit classification rules; they do not
establish general semantic understanding or guarantee distinct behavior for
every descendant. A separate test confirms that a model proposal queue cannot
starve configured uniform exploration. Scheduler tests verify response to
measured rewards; they are not a comparative bug-finding benchmark.

The package-source manifest digest for this local qualification is
`de3c6929bc2fd417ddcf3f0275c848e0d0d5456d7c231af325231dc91d86fbe3`.
It is SHA-256 of a canonical JSON object mapping the nine `evofuzz/*.py`
relative paths to their file SHA-256 values. This is an unsigned source record.
Subsequent changes to validation prose do not change those tested inputs.

Hosted Linux, macOS and Windows CI results remain separate from these local
results. The workflow tests Python 3.11 and 3.12; Windows skips the two explicit
POSIX-only fixtures. Check its actual status before making platform claims.

## Required checks

- All unit/integration tests with `python3 -m unittest discover -v`.
- Lint and Python compilation.
- The buggy escrow campaign, replay and additional minimization.
- A bounded correct escrow campaign with no confirmed findings.
- Both planted mutants caught by the supplied corpus.
- Offline proposal acceptance and opt-in adaptive proposer execution.
- The payment-domain campaign, lineage, archive and learning controls.
- A locally built wheel installed in an isolated environment, with installed
  CLI/version and a target journey exercised outside the checkout.
- Documentation links and a public-source privacy scan.

The protocol's model adapter is tested with a scripted proposer. No live paid
model or external inference service is required or claimed by these checks.
