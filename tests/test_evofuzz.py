import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time
import unittest

from evofuzz import protocol as p
from evofuzz.cli import mutation_test, replay
from evofuzz.config import command, load
from evofuzz.engine import Corpus, Evaluator, confirm, mutate, request, run, shrink
from evofuzz.runner import execute

ROOT = Path(__file__).resolve().parents[1]
PAY = {"op": "pay", "authorized": True}
REFUND = {"op": "refund", "authorized": True}
DENIED = {"op": "pay", "authorized": False}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="evofuzz-test-")
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "examples" / "escrow", self.root / "escrow")
        shutil.copy(ROOT / "examples" / "scripted_proposer.py", self.root)
        self.directory = self.root / "escrow"

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, name="correct", **changes):
        path = self.directory / (name + ".json")
        data = p.read(path)
        data.update(changes)
        p.write(path, data)
        return load(path)

    def evaluator(self, config, budget=150):
        return Evaluator(config, config.fingerprint(), budget)


class ProtocolTests(Fixture):
    def test_json_refuses_duplicates_floats_nan_and_depth(self):
        for raw in ['{"x":1,"x":2}', '1.2', 'NaN', 'Infinity', '[' * 50 + '0' + ']' * 50]:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                p.loads(raw)

    def test_case_rejects_out_of_vocabulary_and_overlength(self):
        cfg = self.config()
        for actions in [[{"op": "drain"}], [PAY] * 9]:
            with self.assertRaises(ValueError):
                p.case(actions, cfg.vocabulary, 8)

    def test_proposal_binding_and_authority_fields(self):
        cfg = self.config()
        req = request(cfg, cfg.fingerprint())
        good = {"schema": "evofuzz/proposal/1", "request_id": req["request_id"],
                "cases": [[PAY, REFUND]], "weights": {"insert": 3}}
        self.assertEqual(p.proposal(good, req, cfg.vocabulary, 8)[0], [[PAY, REFUND]])
        for changes in [{"request_id": "stale"}, {"oracle": ["bypass"]},
                        {"weights": {"insert": 0}}, {"cases": [[{"op": "drain"}]]},
                        {"weights": {"execute-code": 1}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                p.proposal(good | changes, req, cfg.vocabulary, 8)

    def test_bad_config_limits_and_missing_bindings(self):
        for limits in [[], {"unknown": 1}, {"max_actions": True}, {"confirmations": 1}]:
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.config(limits=limits)
        with self.assertRaises(OSError):
            self.config(bindings=["missing.py"], limits={})

    def test_observation_requires_failure_identity(self):
        with self.assertRaises(ValueError):
            p.observation({"schema": "evofuzz/observation/1", "status": "fail", "observation": {}})

    @unittest.skipUnless(os.name == "posix", "POSIX symlink fixture")
    def test_interpreter_symlink_is_preserved_for_virtual_environments(self):
        link = self.root / "python-link"
        link.symlink_to(sys.executable)
        self.assertEqual(command(["./python-link", "target.py"], self.root)[0], str(link))


class SearchTests(Fixture):
    def test_mutation_is_seeded_bounded_and_grammar_valid(self):
        cfg = self.config()
        weights = dict.fromkeys(p.OPERATORS, 1)

        def history(seed):
            rng, actions, records = random.Random(seed), [], []
            for _ in range(300):
                actions, op = mutate(rng, actions, cfg.vocabulary, 8, [[], [PAY]], weights)
                p.case(actions, cfg.vocabulary, 8)
                records.append((actions, op))
            return records

        self.assertEqual(history(7), history(7))
        self.assertNotEqual(history(7), history(8))
        self.assertEqual({op for _, op in history(7)}, set(p.OPERATORS))

    def test_corpus_cap_and_novelty(self):
        corpus = Corpus([[]], 2)
        for actions, cover, distance in [([PAY], "p", 2), ([REFUND], "r", 1)]:
            corpus.observe(actions, {"outcome": "pass", "target": {"value": {"coverage": [cover], "distance": distance}}})
        self.assertEqual(len(corpus.entries), 2)
        self.assertEqual(corpus.coverage, {"p", "r"})

    def test_correct_target_agrees_with_reference(self):
        cfg = self.config()
        ev = self.evaluator(cfg)
        for actions in [[], [PAY], [REFUND, PAY], [DENIED, PAY, REFUND]]:
            self.assertEqual(ev.evaluate(actions)["outcome"], "pass")

    def test_property_bug_replays_and_minimizes_to_two_actions(self):
        cfg = self.config("buggy")
        ev = self.evaluator(cfg)
        actions = [DENIED, PAY, DENIED, REFUND, PAY]
        first = ev.evaluate(actions)
        self.assertEqual(first["kind"], "property")
        self.assertTrue(confirm(ev, actions, first)[0])
        minimal, details = shrink(ev, actions, first["signature"])
        self.assertEqual(minimal, [PAY, REFUND])
        self.assertTrue(details["deletion_minimal"])

    def test_shrink_stays_with_original_failure_identity(self):
        script = 'import json,sys; n=len(json.load(sys.stdin)["actions"]); print(json.dumps({"schema":"evofuzz/observation/1","status":"fail","failure":{"id":"long" if n>=2 else "short"},"observation":n}))'
        cfg = self.config(command=["{python}", "-c", script])
        cfg.commands.pop("oracle")
        ev = self.evaluator(cfg)
        first = ev.evaluate([PAY] * 5)
        minimal, details = shrink(ev, [PAY] * 5, first["signature"])
        self.assertEqual(len(minimal), 2)
        self.assertTrue(details["deletion_minimal"])

    def test_shrink_budget_does_not_claim_minimality(self):
        cfg = self.config("buggy", limits={"max_actions": 8, "shrink_budget": 0})
        ev = self.evaluator(cfg)
        actions = [DENIED, PAY, REFUND]
        signature = ev.evaluate(actions)["signature"]
        minimal, details = shrink(ev, actions, signature)
        self.assertEqual(minimal, actions)
        self.assertFalse(details["deletion_minimal"])

    def test_differential_oracle_finds_silent_semantic_error(self):
        script = 'import json; print(json.dumps({"schema":"evofuzz/observation/1","status":"pass","observation":"wrong"}))'
        cfg = self.config(command=["{python}", "-c", script])
        verdict = self.evaluator(cfg).evaluate([PAY])
        self.assertEqual(verdict["kind"], "differential")

    def test_oracle_failure_is_not_a_target_bug(self):
        cfg = self.config(oracle=["{python}", "-c", "raise SystemExit(3)"])
        verdict = self.evaluator(cfg).evaluate([PAY])
        self.assertEqual(verdict["outcome"], "error")
        self.assertEqual(verdict["reason"], "oracle-unavailable")

    def test_changed_input_is_refused_before_and_after_execution(self):
        cfg = self.config()
        ev = self.evaluator(cfg)
        (self.directory / "target.py").write_text("changed")
        self.assertEqual(ev.evaluate([])["reason"], "declared-input-drift")
        (self.directory / "target.py").write_text("original")
        script = 'from pathlib import Path; Path("target.py").write_text("changed"); print(\'{"schema":"evofuzz/observation/1","status":"pass","observation":[]}\')'
        cfg = self.config(command=["{python}", "-c", script])
        self.assertEqual(self.evaluator(cfg).evaluate([])["reason"], "declared-input-drift")

    def test_flaky_failure_is_not_confirmed(self):
        script = 'import json; from pathlib import Path; p=Path("count"); n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); r={"schema":"evofuzz/observation/1","status":"fail" if n%2==0 else "pass","observation":[]}; r.update({"failure":{"id":"flaky"}} if n%2==0 else {}); print(json.dumps(r))'
        cfg = self.config(command=["{python}", "-c", script])
        cfg.commands.pop("oracle")
        stable, records = confirm(self.evaluator(cfg), [])
        self.assertFalse(stable)
        self.assertEqual([r["outcome"] for r in records], ["failure", "pass"])

    def test_offline_llm_proposal_replay_and_binding_drift(self):
        cfg = self.config("buggy")
        req = request(cfg, cfg.fingerprint())
        proposal = {"schema": "evofuzz/proposal/1", "request_id": req["request_id"],
                    "cases": [[PAY, REFUND]]}
        out = self.root / "run"
        summary = run(cfg, out, seed=7, budget=12, proposals=proposal)
        self.assertEqual(summary["findings"], ["finding-0001.json"])
        self.assertTrue(replay(cfg, out)["matched"])
        (self.directory / "reference.py").write_text("changed")
        with self.assertRaises(ValueError):
            replay(cfg, out)

    def test_periodic_proposer_is_opt_in_and_logged(self):
        cfg = self.config("guided-demo")
        out = self.root / "guided"
        summary = run(cfg, out, budget=12, enable_proposer=True)
        self.assertGreater(summary["proposer_calls"], 0)
        self.assertTrue(summary["findings"])
        self.assertEqual(p.read(out / "proposal-0001.json")["status"], "accepted")
        disabled = run(cfg, self.root / "disabled", budget=2)
        self.assertEqual(disabled["proposer_calls"], 0)

    def test_evolution_finds_two_step_bug_without_supplied_attack(self):
        summary = run(self.config("buggy"), self.root / "evolved", seed=7, budget=60)
        self.assertTrue(summary["findings"])
        finding = p.read(self.root / "evolved" / summary["findings"][0])
        self.assertEqual(finding["actions"], [PAY, REFUND])

    def test_malformed_response_stops_search(self):
        cfg = self.config(command=["{python}", "-c", "print('not json')"])
        summary = run(cfg, self.root / "bad", budget=10)
        self.assertEqual(summary["status"], "stopped-on-execution-error")
        self.assertEqual(summary["findings"], [])

    def test_insufficient_confirmation_budget_is_inconclusive(self):
        cfg = self.config("buggy", seeds=[[PAY, REFUND]])
        summary = run(cfg, self.root / "insufficient", budget=1)
        self.assertEqual(summary["findings"], [])
        self.assertTrue(summary["inconclusive_candidates"])
        self.assertEqual(summary["events"][0]["status"], "unconfirmed-budget")

    def test_large_observation_findings_remain_readable_and_replayable(self):
        script = 'import json; print(json.dumps({"schema":"evofuzz/observation/1","status":"fail","failure":{"id":"large"},"observation":["x"*8192]*12}))'
        cfg = self.config(command=["{python}", "-c", script],
                          limits={"confirmations": 5, "output_bytes": 262144, "shrink_budget": 0})
        cfg.commands.pop("oracle")
        out = self.root / "large"
        summary = run(cfg, out, budget=5)
        self.assertEqual(len(summary["findings"]), 1)
        self.assertEqual(len(p.read(out / summary["findings"][0])["replays"]), 5)
        self.assertTrue(replay(cfg, out)["matched"])

    def test_shrink_execution_error_does_not_claim_minimality(self):
        script = 'import json,sys; n=len(json.load(sys.stdin)["actions"]); print("not json" if n==1 else json.dumps({"schema":"evofuzz/observation/1","status":"fail","failure":{"id":"same"},"observation":n}))'
        cfg = self.config(command=["{python}", "-c", script])
        cfg.commands.pop("oracle")
        ev = self.evaluator(cfg)
        first = ev.evaluate([PAY] * 3)
        _, detail = shrink(ev, [PAY] * 3, first["signature"])
        self.assertFalse(detail["deletion_minimal"])

    def test_invalid_adaptive_proposal_is_logged_and_cannot_edit_target(self):
        script = 'import json,sys; r=json.load(sys.stdin); print(json.dumps({"schema":"evofuzz/proposal/1","request_id":r["request_id"],"cases":[],"oracle":"bypass"}))'
        cfg = self.config(proposer=["{python}", "-c", script], limits={"proposer_interval": 1})
        before = cfg.fingerprint()
        out = self.root / "bad-proposal"
        run(cfg, out, budget=4, enable_proposer=True)
        self.assertEqual(p.read(out / "proposal-0001.json")["status"], "rejected")
        self.assertEqual(cfg.fingerprint(), before)


class MutationTests(Fixture):
    def test_kills_both_deliberately_faulty_variants(self):
        result = mutation_test(self.config(), [[PAY, REFUND], [DENIED]])
        self.assertEqual([m["status"] for m in result["mutants"]], ["killed", "killed"])

    def test_identical_variant_survives_and_timeout_is_error(self):
        cfg = self.config(mutants=[
            {"id": "same", "command": ["{python}", "target.py"]},
            {"id": "timeout", "command": ["{python}", "-c", "import time; time.sleep(5)"]}],
            limits={"timeout_ms": 200})
        result = mutation_test(cfg, [[PAY]])
        self.assertEqual([m["status"] for m in result["mutants"]], ["survived", "error"])

    def test_baseline_failure_prevents_mutant_scoring(self):
        result = mutation_test(self.config("buggy"), [[PAY, REFUND]])
        self.assertEqual(result["status"], "baseline-failed")
        self.assertEqual(result["mutants"], [])


class ProcessTests(Fixture):
    def test_output_limit_applies_to_both_streams(self):
        command = [sys.executable, "-c", "import sys; sys.stderr.write('x'*200000)"]
        result = execute(command, b"{}", self.root, 2000, 1024)
        self.assertEqual(result.status, "output_limit")
        self.assertLessEqual(len(result.stdout) + len(result.stderr), 1024)

    def test_deadline_also_covers_blocked_stdin(self):
        start = time.monotonic()
        result = execute([sys.executable, "-c", "import time; time.sleep(5)"],
                         b"x" * 200_000, self.root, 100, 1024)
        self.assertEqual(result.status, "timeout")
        self.assertLess(time.monotonic() - start, 2)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group guarantee")
    def test_timeout_kills_ordinary_descendants(self):
        child = 'import time; from pathlib import Path; time.sleep(.5); Path("escaped-marker").write_text("bad")'
        parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(5)'
        result = execute([sys.executable, "-c", parent], b"{}", self.root, 150, 1024)
        self.assertEqual(result.status, "timeout")
        time.sleep(0.6)
        self.assertFalse((self.root / "escaped-marker").exists())

    def test_nonzero_target_exit_is_a_replayable_crash_candidate(self):
        cfg = self.config(command=["{python}", "-c", "raise SystemExit(7)"])
        stable, records = confirm(self.evaluator(cfg), [])
        self.assertTrue(stable)
        self.assertEqual(records[0]["kind"], "process-exit")


if __name__ == "__main__":
    unittest.main()
