from pathlib import Path
import random
import shutil
import tempfile
import unittest
from unittest.mock import patch

from evofuzz import protocol as p
from evofuzz.config import load
from evofuzz.domain import Domain
from evofuzz.engine import Evaluator, run
from evofuzz.evolution import Scheduler
from evofuzz.states import START, StateGraph

ROOT = Path(__file__).resolve().parents[1]
UP, DOWN, STAY = {"op": "up"}, {"op": "down"}, {"op": "stay"}
VOCABULARY = [UP, DOWN, STAY]


class StateGraphTests(unittest.TestCase):
    def test_records_shortest_sequences_transitions_and_novelty(self):
        graph = StateGraph(VOCABULARY)
        self.assertEqual(graph.observe([STAY, UP, UP], ["0", "1", "2"]), (3, 3))
        self.assertEqual(graph.prefix["1"], [STAY, UP])
        self.assertEqual(graph.observe([UP], ["1"]), (0, 1))
        self.assertEqual(graph.prefix["1"], [UP])  # A shorter witness replaces the longer one.
        self.assertEqual(graph.observe([UP], ["1"]), (0, 0))

    def test_conflicting_successors_mark_an_incomplete_label(self):
        graph = StateGraph(VOCABULARY)
        graph.observe([UP, UP], ["same", "a"])
        graph.observe([DOWN, UP], ["same", "b"])
        self.assertEqual(len(graph.conflicts), 1)
        conflict = graph.conflicts[0]
        self.assertEqual(conflict["successors"], ["a", "b"])
        self.assertEqual(conflict["witnesses"], [[UP, UP], [DOWN, UP]])
        self.assertIn("same", graph.unreliable)
        self.assertFalse(graph.expandable("same"))
        self.assertIsNone(graph.closed_depth())

    def test_plan_tries_untried_actions_from_known_states_only(self):
        graph = StateGraph(VOCABULARY)
        graph.observe([UP], ["1"])
        rng = random.Random(3)
        for _ in range(20):
            actions, state = graph.plan(rng, max_actions=4)
            self.assertIn(state, (START, "1"))
            self.assertEqual(actions[:len(graph.prefix[state])], graph.prefix[state])
            self.assertNotIn(p.digest(actions[len(graph.prefix[state])]), graph.tried[state])
            self.assertLessEqual(len(actions), 4)

    def test_failed_and_stopped_executions_are_not_expanded(self):
        graph = StateGraph(VOCABULARY)
        graph.observe([UP, UP], ["1", "broken"], stopped=True)
        graph.observe([DOWN, UP, UP], ["early"])  # The target stopped after one of three actions.
        self.assertEqual(graph.terminal, {"broken", "early"})
        self.assertFalse(graph.expandable("broken"))
        rng = random.Random(1)
        for _ in range(30):
            planned = graph.plan(rng, max_actions=6)
            self.assertNotIn(planned[1], graph.terminal)

    def test_closed_depth_and_full_expansion_on_a_finite_machine(self):
        graph = StateGraph(VOCABULARY)
        def step(state, action):
            return {"up": min(state + 1, 2), "down": max(state - 1, 0), "stay": state}[action["op"]]
        rng = random.Random(0)
        self.assertEqual(graph.closed_depth(), 0)
        while (planned := graph.plan(rng, max_actions=6)) is not None:
            actions, state = planned
            current, labels = 0, []
            for action in actions:
                current = step(current, action)
                labels.append(str(current))
            graph.observe(actions, labels)
        summary = graph.summary()
        self.assertTrue(summary["fully_expanded"])
        self.assertEqual(summary["states"], 3)
        self.assertEqual(summary["transitions"], 3 * 4)  # Start and three labels, three actions each.
        self.assertEqual(summary["closed_depth"], 3)  # Levels: the start, one action, two actions.

    def test_shortcut_reaches_the_failing_step_by_the_shortest_known_sequence(self):
        graph = StateGraph(VOCABULARY)
        graph.observe([UP], ["1"])
        failing = [STAY, DOWN, UP, STAY, DOWN]
        labels = ["0", "0", "1", "1", "bad"]
        graph.observe(failing, labels, stopped=True)
        self.assertEqual(graph.shortcut(failing, labels), [UP, DOWN])
        self.assertIsNone(graph.shortcut([UP, DOWN], ["1", "bad"]))

    def test_labels_are_bounded_strings_and_never_the_start_name(self):
        graph = StateGraph(VOCABULARY)
        for labels in ([START], [""], ["x" * 129], [3]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                graph.observe([UP], labels)
        with self.assertRaises(ValueError):
            graph.observe([UP], ["a", "b"])

    def test_parametric_domains_sample_untried_actions_and_skip_closure_claims(self):
        pay = {"op": "pay", "id": "A", "amount": 1}
        domain = Domain([pay], {"parameters": {"id": {"values": ["A", "B"]}, "amount": {"min": 0, "max": 2}}})
        graph = StateGraph([pay], domain)
        graph.observe([pay], ["paid"])
        actions, _ = graph.plan(random.Random(5), max_actions=3)
        p.case(actions, [pay], 3, domain)
        self.assertIsNone(graph.closed_depth())

    def test_artifact_stays_within_its_byte_budget(self):
        graph = StateGraph(VOCABULARY)
        for n in range(200):
            graph.observe([UP] * 20, [f"s{n}-{i}" for i in range(20)])
        artifact = graph.artifact(byte_limit=2000)
        self.assertLessEqual(len(p.canonical(artifact).encode("utf-8")) + 1, 2000)
        self.assertGreater(artifact["shortest_omitted"], 0)

    def test_long_conflict_witnesses_fit_complete_artifact_budget(self):
        action = {"op": "step", "padding": "x" * 224}
        graph = StateGraph([action])
        actions = [action] * 128
        p.case(actions, [action], 128)
        labels = [f"state-{i}" for i in range(128)]
        graph.observe(actions, labels)
        graph.observe(actions, [f"other-{i}" if i >= 97 and i % 2 else label
                                for i, label in enumerate(labels)])
        self.assertEqual(len(graph.conflicts), 16)
        artifact = graph.artifact()
        self.assertGreater(artifact["conflicts_omitted"], 0)
        self.assertEqual(len(artifact["conflicts"]) + artifact["conflicts_omitted"], 16)
        self.assertEqual(len(artifact["shortest"]) + artifact["shortest_omitted"],
                         len(graph.prefix) - 1)
        self.assertEqual(artifact["summary"], graph.summary())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "states.json"
            p.write(path, artifact)
            self.assertLessEqual(path.stat().st_size, 900_000)
            self.assertEqual(p.read(path), artifact)

    def test_artifact_budgets_escaped_labels_and_metadata(self):
        graph = StateGraph(VOCABULARY)
        graph.observe([UP, DOWN], ['\"' * 128, "é" * 128])
        for limit in (500, 1000, 2000):
            artifact = graph.artifact(limit)
            self.assertLessEqual(len(p.canonical(artifact).encode("utf-8")) + 1, limit)
        with self.assertRaisesRegex(ValueError, "too small for metadata"):
            graph.artifact(1)


class ProtocolAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="evofuzz-states-")
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "examples/payments", self.root / "payments")

    def tearDown(self):
        self.tmp.cleanup()

    def test_observation_state_labels_are_validated(self):
        base = {"schema": "evofuzz/observation/1", "status": "pass", "observation": []}
        p.observation(base | {"states": ["a", "b"]})
        for states in (["<start>"], [""], [1], ["a"] * 129, "a"):
            with self.subTest(states=states), self.assertRaises(ValueError):
                p.observation(base | {"states": states})

    def test_frontier_settings_are_bounded_and_add_one_operator(self):
        path = self.root / "payments/frontier.json"
        cfg = load(path)
        self.assertIn("frontier", cfg.operators)
        self.assertNotIn("frontier", load(self.root / "payments/target.json").operators)
        for changes in ({"state_frontier": "yes"}, {"frontier_tail": 129}, {"frontier_percent": 101},
                        {"frontier_depth": 2}):
            data = p.read(path)
            data["archive"] = data["archive"] | changes
            p.write(path, data)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                load(path)

    def test_more_labels_than_actions_is_a_protocol_error(self):
        script = self.root / "payments/liar.py"
        script.write_text('import json, sys\njson.load(sys.stdin)\nprint(json.dumps({"schema": '
                          '"evofuzz/observation/1", "status": "pass", "observation": [], "states": ["a", "b"]}))\n')
        path = self.root / "payments/liar.json"
        data = p.read(self.root / "payments/frontier.json")
        data.update(command=["{python}", "liar.py"], bindings=["liar.py"])
        p.write(path, data)
        cfg = load(path)
        verdict = Evaluator(cfg, cfg.fingerprint(), 5).evaluate([cfg.vocabulary[0]])
        self.assertEqual((verdict["outcome"], verdict["reason"]), ("error", "protocol_error"))


class FrontierCampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="evofuzz-frontier-")
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "examples/payments", self.root / "payments")
        shutil.copytree(ROOT / "benchmarks", self.root / "benchmarks")

    def tearDown(self):
        self.tmp.cleanup()

    def test_setup_breaking_shortcut_preserves_confirmed_finding(self):
        script = self.root / "setup.py"
        script.write_text(
            'import json, sys\n'
            'actions = json.load(sys.stdin)["actions"]\n'
            'failed = actions[-1]["op"] == "bug"\n'
            'value = {"schema": "evofuzz/observation/1", '
            '"status": "fail" if failed else "pass", "observation": [], '
            '"states": ["bad" if a["op"] == "bug" else "ready" for a in actions]}\n'
            'if failed: value["failure"] = {"id": "bug", "message": "failed"}\n'
            'print(json.dumps(value))\n')
        actions = [{"op": op} for op in ("init1", "init2", "bug")]
        path = self.root / "setup.json"
        p.write(path, {"schema": "evofuzz/target/1", "objective": "Find the bug",
                       "command": ["{python}", "setup.py"], "bindings": ["setup.py"],
                       "vocabulary": actions, "seeds": [actions],
                       "domain": {"setup": actions[:2]},
                       "limits": {"shrink_budget": 0}, "archive": {"state_frontier": True}})
        output = self.root / "setup-run"
        summary = run(load(path), output, seed=0, budget=10)
        self.assertTrue(summary["findings"])
        self.assertEqual(p.read(output / "summary.json"), summary)
        finding = p.read(output / summary["findings"][0])
        self.assertEqual(finding["actions"], actions)
        self.assertFalse(finding["minimization"]["state_shortcut"]["tried"])
        self.assertIn("skipped", finding["minimization"]["state_shortcut"])

    def test_uniform_exploration_reaches_scheduler_despite_full_frontier_share(self):
        path = self.root / "benchmarks/lock-frontier.json"
        data = p.read(path)
        data["archive"].update(exploration_percent=100, frontier_percent=100, frontier_tail=0)
        p.write(path, data)
        output = self.root / "uniform"
        with patch.object(Scheduler, "choose", autospec=True, side_effect=Scheduler.choose) as choose:
            run(load(path), output, seed=0, budget=20)
        records = [p.loads(line) for line in (output / "lineage.jsonl").read_text().splitlines()]
        attempts = [r for r in records if r["operator"] not in ("seed", "minimize")]
        self.assertTrue(attempts)
        self.assertTrue(all(r["exploration"] for r in attempts))
        self.assertEqual(choose.call_count, len(attempts))
        self.assertTrue(any(r["operator"] != "frontier" for r in attempts))

    def test_frontier_opens_the_combination_lock_and_records_its_graph(self):
        cfg = load(self.root / "benchmarks/lock-frontier.json")
        output = self.root / "lock"
        summary = run(cfg, output, seed=0, budget=200)
        self.assertTrue(summary["findings"], summary)
        graph = summary["state_graph"]
        self.assertEqual(graph["conflicts"], 0)
        self.assertGreaterEqual(graph["states"], 6)
        finding = p.read(output / summary["findings"][0])
        self.assertEqual(len(finding["actions"]), 6)
        self.assertIn("state_shortcut", finding["minimization"])
        states = p.read(output / "states.json")
        self.assertEqual(states["schema"], "evofuzz/state-graph/1")
        self.assertFalse(summary["exhaustive"])
        records = [p.loads(line) for line in (output / "lineage.jsonl").read_text().splitlines()]
        frontier = [r for r in records if r["operator"] == "frontier"]
        self.assertTrue(frontier)
        self.assertTrue(all(r["parents"] == [] and "frontier_state" in r for r in frontier))

    def test_frontier_finds_the_double_payout_in_the_parametric_domain(self):
        cfg = load(self.root / "payments/frontier.json")
        summary = run(cfg, self.root / "pay", seed=7, budget=120)
        self.assertTrue(summary["findings"])
        self.assertIsNone(summary["state_graph"]["closed_depth"])  # Parameters make closure undefined.

    def test_a_coarse_label_is_reported_as_conflicts_not_as_a_bug(self):
        script = self.root / "benchmarks/coarse.py"
        source = (self.root / "benchmarks/lock.py").read_text()
        script.write_text(source.replace('states.append(f"progress:{progress}")',
                                         'states.append("progress:" + str(min(progress, 1)))'))
        data = p.read(self.root / "benchmarks/lock-frontier.json")
        data.update(command=["{python}", "coarse.py", "--states"], bindings=["coarse.py"])
        path = self.root / "benchmarks/coarse.json"
        p.write(path, data)
        summary = run(load(path), self.root / "coarse", seed=0, budget=150)
        self.assertGreater(summary["state_graph"]["conflicts"], 0)
        self.assertIsNone(summary["state_graph"]["closed_depth"])
        self.assertFalse(summary["findings"])  # The correct lock never fails, whatever the labels say.


if __name__ == "__main__":
    unittest.main()
