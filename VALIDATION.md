# Validation scope

This record describes the initial implementation's local checks. It is not a
formal proof, external audit or model-guidance benchmark.

The suite exercises the real subprocess boundary, complete example workflows
and malformed/adversarial protocol cases. The deliberately faulty escrow
variants are demonstration defects, not newly discovered product vulnerabilities.

Local qualification passed on Linux with Python 3.12.3:

| Check | Result |
|---|---|
| Unit/integration suite | 31 passed |
| Lint and Python compilation | Passed |
| Unguided buggy-escrow campaign | Found the planted conservation defect |
| Reduced witness | Authorized pay, then authorized refund |
| Replay and further minimization | Passed; two-action witness retained |
| Correct-escrow campaign | No findings in 40 case evaluations |
| Mutation testing | Both supplied faulty variants killed |
| Offline proposals and adaptive command interface | Passed |
| Installed wheel outside checkout | Version, search and replay passed |
| Documentation links, agent skill format and public-source scan | Passed |

The campaign used seed 7 and an 80-evaluation budget for the buggy target.
These counts include confirmation and minimization, not just search proposals.
The absence of findings in the correct target's bounded campaign is not a
proof of safety. The two planted mutants do not establish general mutation
coverage. Model-guidance effectiveness remains unmeasured.

The package-source manifest digest for this local qualification is
`57cbe6e2d6bc7c469a6a5a0342590226c88ebd470a753350aedc82f77125a4b3`.
It is SHA-256 of a canonical JSON object mapping the seven `evofuzz/*.py`
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
- A locally built wheel installed in an isolated environment, with installed
  CLI/version and a target journey exercised outside the checkout.
- Documentation links and a public-source privacy scan.

The protocol's model adapter is tested with a scripted proposer. No live paid
model or external inference service is required or claimed by these checks.
