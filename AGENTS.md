# Repository guidance

Keep the search advisory and the target/oracle contract authoritative. Never
turn a timeout, parser error, source drift, unstable result or empty campaign
into a safety claim. The fuzzer is not an OS sandbox.

Keep process requests and proposals bounded. Model proposals cannot change
commands, limits, objective, bindings or oracle rules. Preserve failing inputs
and evidence; do not silently rewrite an earlier run.

Run affected unit tests for code changes. Run `python3 -m unittest discover -v`
before a version/release, together with the documented escrow commands. Do not
restart unrelated expensive checks for prose or metadata edits. Lint when
available with `ruff check evofuzz examples tests`.

Do not commit run artifacts, local paths, credentials or private research.
Do not add model-provider dependencies or send target data externally without
an explicit opt-in. Keep the portable package independent of other projects.
