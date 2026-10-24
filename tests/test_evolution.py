import copy
from pathlib import Path
import random
import shutil
import tempfile
import unittest

from evofuzz import protocol as p
from evofuzz.config import load
from evofuzz.domain import Domain
from evofuzz.engine import mutate, request, run
from evofuzz.evolution import Corpus, Scheduler, shape

ROOT = Path(__file__).resolve().parents[1]
PAY = {"op": "pay", "id": "A", "amount": 1}
OTHER = PAY | {"id": "B"}
PARAMETERS = {"id": {"values": ["A", "B"]}, "amount": {"min": 0, "max": 2}}


def observed(family, distance=1):
    return {"outcome": "pass", "target": {"value": {"features": {"family": family},
            "distance": distance, "coverage": [], "observation": "same"}}}


class DomainTests(unittest.TestCase):
    def domain(self, **extra):
        return Domain([PAY, {"op": "restart"}], {"parameters": PARAMETERS,
                      "identity_fields": ["id"]} | extra)

    def test_parameters_admit_new_values_but_not_new_operations_or_fields(self):
        domain = self.domain()
        p.case([OTHER | {"amount": 2}], domain.vocabulary, 8, domain)
        for action in [PAY | {"amount": True}, PAY | {"amount": 3}, PAY | {"id": "C"},
                       PAY | {"op": "drain"}, PAY | {"extra": 1}]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                p.case([action], domain.vocabulary, 8, domain)

    def test_invalid_domains_are_rejected(self):
        for data in [[], {"parameters": {"op": {"values": ["pay"]}}},
                     {"parameters": {"amount": {"min": 0, "max": 1_000_000_001}}},
                     {"identity_fields": ["missing"]},
                     {"blocks": [{"name": "bad", "actions": [{"op": "drain"}]}]}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                Domain([PAY], data)

    def test_enum_boolean_and_integer_are_distinct(self):
        domain = Domain([{"op": "pay", "authorized": False}],
                        {"parameters": {"authorized": {"values": [False, True]}}})
        self.assertTrue(domain.accepts({"op": "pay", "authorized": True}))
        self.assertFalse(domain.accepts({"op": "pay", "authorized": 1}))

    def test_rebinding_creates_shared_and_distinct_identity_families(self):
        domain, rng = self.domain(), random.Random(7)
        patterns = set()
        for _ in range(100):
            actions = [copy.deepcopy(PAY), copy.deepcopy(PAY)]
            domain.rebind(rng, actions)
            domain.validate(actions)
            patterns.add(tuple(a["id"] for a in actions))
        self.assertTrue({("A", "B"), ("B", "A"), ("B", "B")} <= patterns)

    def test_parameter_mutation_hits_boundaries(self):
        domain, rng = self.domain(), random.Random(9)
        seen = set()
        for _ in range(100):
            actions = [copy.deepcopy(PAY)]
            domain.parameter(rng, actions)
            seen.add(actions[0]["amount"])
        self.assertEqual(seen, {0, 1, 2})

    def test_every_operator_preserves_setup_and_domain(self):
        setup = [{"op": "restart"}]
        domain = self.domain(setup=setup, blocks=[{"name": "recover", "actions": setup}])
        rng = random.Random(4)
        for op in domain.operators:
            for _ in range(20):
                actions, used = mutate(rng, setup + [PAY, PAY], domain.vocabulary, 8,
                                       [setup + [PAY]], dict.fromkeys(domain.operators, 1), domain, op)
                self.assertEqual(used, op)
                self.assertEqual(actions[:1], setup)
                p.case(actions, domain.vocabulary, 8, domain)
        with self.assertRaises(ValueError):
            p.case([PAY], domain.vocabulary, 8, domain)


class ArchiveTests(unittest.TestCase):
    def test_reclaims_extra_slots_before_losing_a_family(self):
        corpus = Corpus([], 4)
        corpus.observe([PAY], observed("replay"))
        corpus.observe([PAY, PAY], observed("replay"))
        corpus.observe([OTHER], observed("identity"))
        corpus.observe([{"op": "restart"}], observed("recovery"))
        corpus.observe([PAY | {"amount": 0}], observed("authorization"))
        names = {f["descriptor"]["values"]["family"]["value"] for f in corpus.summaries()}
        self.assertEqual(names, {"replay", "identity", "recovery", "authorization"})
        self.assertEqual(len(corpus.entries), 4)

    def test_same_behavior_retains_structurally_different_representatives(self):
        corpus = Corpus([], 8)
        corpus.observe([PAY], observed("same"))
        corpus.observe([OTHER, PAY], observed("same"))
        self.assertEqual(len(corpus.summaries()), 1)
        self.assertEqual(len(corpus.entries), 2)
        self.assertNotEqual(shape(corpus.entries[0]), shape(corpus.entries[1]))

    def test_error_does_not_enter_archive_or_earn_reward(self):
        corpus = Corpus([[]], 8)
        before = corpus.entries
        result = corpus.observe([PAY], {"outcome": "error", "reason": "timeout"})
        self.assertEqual(result["reward"], 0)
        self.assertEqual(corpus.entries, before)

    def test_missing_features_are_labelled_structural(self):
        corpus = Corpus([[]], 8)
        corpus.observe([PAY], {"outcome": "pass", "target": {"value": {"observation": []}}})
        self.assertTrue(all(f["descriptor"]["source"] == "structure" for f in corpus.summaries()))

    def test_corpus_memory_stays_bounded(self):
        corpus = Corpus([], 4)
        for i in range(100):
            corpus.observe([PAY | {"amount": i}], observed(str(i)))
        self.assertLessEqual(len(corpus.entries), 4)
        self.assertLessEqual(len(corpus.family_uses), 4)

    def test_parent_selection_uses_offspring_rewards_with_uniform_exploration(self):
        corpus = Corpus([], 8)
        corpus.observe([PAY], observed("productive"))
        corpus.observe([OTHER], observed("other"))
        productive = corpus.family([PAY], observed("productive"))[0]
        corpus.credit(productive, 64)
        rng = random.Random(4)
        selected = sum(corpus.choose(rng)["family_id"] == productive for _ in range(200))
        self.assertGreater(selected, 120)
        explored = sum(corpus.choose(rng, explore=True, priors={productive: 100})["family_id"] == productive
                       for _ in range(200))
        self.assertTrue(60 < explored < 140)


class LearningTests(unittest.TestCase):
    def test_scheduler_learns_per_family_and_exploration_ignores_priors(self):
        scheduler = Scheduler(("insert", "delete"))
        for _ in range(100):
            scheduler.record("replay", "insert", 8)
            scheduler.record("replay", "delete", 0)
            scheduler.record("recovery", "delete", 8)
            scheduler.record("recovery", "insert", 0)
        rng = random.Random(3)
        priors = {"insert": 1, "delete": 1}
        self.assertGreater(sum(scheduler.choose(rng, "replay", priors) == "insert" for _ in range(200)), 180)
        self.assertGreater(sum(scheduler.choose(rng, "recovery", priors) == "delete" for _ in range(200)), 180)
        count = sum(scheduler.choose(rng, "replay", {"insert": 100, "delete": 1}, explore=True) == "insert"
                    for _ in range(200))
        self.assertTrue(60 < count < 140)

    def test_confirmed_failure_bonus_does_not_inflate_attempt_count(self):
        scheduler = Scheduler(("insert",))
        scheduler.record("x", "insert", 0)
        scheduler.record("x", "insert", 32, count_attempt=False, newly_productive=True)
        self.assertEqual(scheduler.stats["x"]["insert"], {"attempts": 1, "productive": 1, "reward": 32})

    def test_scheduler_contexts_are_bounded(self):
        scheduler = Scheduler(("insert",))
        for i in range(400):
            scheduler.record(str(i), "insert", 0)
        self.assertEqual(len(scheduler.stats), 257)
        self.assertIn("overflow", scheduler.stats)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="evofuzz-evolution-")
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "examples/payments", self.root / "payments")
        self.config = load(self.root / "payments/target.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_request_and_proposal_expose_domain_and_bound_family_steering(self):
        cfg = self.config
        req = request(cfg, cfg.fingerprint())
        self.assertIn("rebind", req["operators"])
        self.assertEqual(req["domain"]["parameters"]["id"]["values"], ["A", "B"])
        action = cfg.vocabulary[0] | {"id": "B", "amount": 2}
        good = {"schema": "evofuzz/proposal/1", "request_id": req["request_id"], "cases": [[action]],
                "family_weights": {req["families"][0]["family_id"]: 4}}
        p.proposal(good, req, cfg.vocabulary, 10, cfg.domain)
        for changes in [{"family_weights": {"invented-family": 4}},
                        {"family_weights": {req["families"][0]["family_id"]: 0}},
                        {"domain": {"allow": "everything"}}]:
            with self.assertRaises(ValueError):
                p.proposal(good | changes, req, cfg.vocabulary, 10, cfg.domain)

    def test_pay_pay_branches_into_families_with_replayable_lineage(self):
        output = self.root / "run"
        summary = run(self.config, output, seed=7, budget=200)
        self.assertTrue(summary["findings"])
        archive = p.read(output / "archive.json")
        names = {f["descriptor"]["values"].get("family", {}).get("value") for f in archive["families"]}
        self.assertTrue({"replay", "identity", "authorization", "reversal", "recovery"} <= names, names)
        records = [p.loads(line) for line in (output / "lineage.jsonl").read_text().splitlines()]
        events = set()
        for record in records:
            self.assertTrue(set(record["parent_events"]) <= events, record)
            events.add(record["event_id"])
            if record["operator"] == "splice":
                self.assertEqual(len(record["parents"]), 2)
            if record["operator"] == "random":
                self.assertEqual(record["parents"], [])
        self.assertTrue(any(r["generation"] >= 2 for r in records))
        self.assertTrue(any(r["status"] == "duplicate" for r in records))
        learning = p.read(output / "learning.json")
        self.assertTrue(any(s["productive"] for context in learning["operators"].values() for s in context.values()))

    def test_queued_model_cases_cannot_starve_uniform_exploration(self):
        path = self.config.path
        data = p.read(path)
        data["archive"]["exploration_percent"] = 100
        data["limits"]["shrink_budget"] = 0
        p.write(path, data)
        cfg = load(path)
        req = request(cfg, cfg.fingerprint())
        proposed = cfg.vocabulary[0] | {"id": "B"}
        proposal = {"schema": "evofuzz/proposal/1", "request_id": req["request_id"], "cases": [[proposed]] * 16}
        output = self.root / "exploration"
        run(cfg, output, seed=7, budget=12, proposals=proposal)
        records = [p.loads(line) for line in (output / "lineage.jsonl").read_text().splitlines()]
        self.assertTrue(any(r.get("exploration") for r in records))
        self.assertFalse(any(r["operator"] == "proposal" for r in records))


if __name__ == "__main__":
    unittest.main()
