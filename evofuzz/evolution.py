"""Bounded behavioral archive and online offspring-productivity scheduling."""
from __future__ import annotations

import copy

from . import protocol as p


def shape(actions):
    tokens = [p.digest(a) for a in actions]
    return set(tokens) | {p.digest([a, b]) for a, b in zip(tokens, tokens[1:])}


def structural_family(actions):
    operations = [a.get("op", "object") if type(a) is dict else type(a).__name__ for a in actions]
    operations = [op if type(op) is str and len(op) <= 128 else p.digest(op)[:16] for op in operations]
    runs = [str(op) for i, op in enumerate(operations) if i == 0 or op != operations[i - 1]]
    return {"structural_pattern": runs[:8], "length_bucket": min(7, len(actions).bit_length())}


class Corpus:
    def __init__(self, seeds, cap, settings=None):
        self.cap = cap
        self.settings = settings or {"features": ["family"], "per_family": min(2, cap), "exploration_percent": 20}
        self.records = {}
        self.coverage = set()
        self.distance = 1_000_001
        self.family_uses = {}
        self.family_rewards = {}
        for actions in seeds:
            self.add(actions)

    @property
    def entries(self):
        return [copy.deepcopy(r["actions"]) for r in self.records.values()]

    def family(self, actions, result=None):
        features = (result or {}).get("target", {}).get("value", {}).get("features", {})
        names = self.settings["features"]
        if any(name in features for name in names):
            descriptor = {"source": "target", "values": {name: {"value": features[name]} if name in features
                          else {"missing": True} for name in names}}
        else:
            descriptor = {"source": "structure", "values": structural_family(actions)}
        return p.digest(descriptor), descriptor

    @staticmethod
    def quality(record):
        return (record["confirmed"], -record["distance"], len(record["coverage"]), -len(record["actions"]))

    def _trim(self):
        families = {}
        for entry in self.records.values():
            families.setdefault(entry["family_id"], []).append(entry)
        for entries in families.values():
            champion = max(entries, key=lambda r: (self.quality(r), r["case_id"]))
            chosen = [champion]
            while len(chosen) < self.settings["per_family"] and len(chosen) < len(entries):
                candidates = [e for e in entries if e not in chosen]
                diverse = max(candidates, key=lambda e: (
                    min(len(shape(e["actions"]) ^ shape(c["actions"])) for c in chosen),
                    self.quality(e), e["case_id"]))
                chosen.append(diverse)
            for entry in entries:
                if entry not in chosen:
                    self.records.pop(entry["case_id"], None)
        while len(self.records) > self.cap:
            counts = {}
            for entry in self.records.values():
                counts[entry["family_id"]] = counts.get(entry["family_id"], 0) + 1
            extras = [e for e in self.records.values() if counts[e["family_id"]] > 1]
            candidates = extras or list(self.records.values())
            victim = min(candidates, key=lambda e: (self.quality(e),
                         self.family_rewards.get(e["family_id"], 0) * 16 // (self.family_uses.get(e["family_id"], 0) + 1),
                         e["case_id"]))
            del self.records[victim["case_id"]]
        active = {e["family_id"] for e in self.records.values()}
        self.family_uses = {k: v for k, v in self.family_uses.items() if k in active}
        self.family_rewards = {k: v for k, v in self.family_rewards.items() if k in active}

    def add(self, actions, result=None, generation=0, confirmed=False, event_id=None):
        identity = p.digest(actions)
        family_id, descriptor = self.family(actions, result)
        value = (result or {}).get("target", {}).get("value", {})
        old = self.records.get(identity)
        self.records[identity] = {"case_id": identity, "actions": copy.deepcopy(actions),
            "family_id": family_id, "family": descriptor, "generation": generation,
            "event_id": event_id or (old or {}).get("event_id"),
            "distance": value.get("distance", 1_000_000), "coverage": sorted(set(value.get("coverage", []))),
            "confirmed": confirmed or bool(old and old["confirmed"])}
        self._trim()
        return identity in self.records

    def observe(self, actions, result, generation=0, event_id=None):
        if result["outcome"] not in ("pass", "failure"):
            return {"reward": 0, "retained": False, "family_id": None}
        value = result.get("target", {}).get("value", {})
        coverage = set(value.get("coverage", []))
        novelty = len(coverage - self.coverage)
        family_id, _ = self.family(actions, result)
        entries = [e for e in self.records.values() if e["family_id"] == family_id]
        new_family = not entries
        new_structure = all(shape(actions) != shape(e["actions"]) for e in entries)
        improved = value.get("distance", 1_000_000) < min((e["distance"] for e in entries), default=1_000_001)
        self.coverage.update(sorted(coverage - self.coverage)[:max(0, 4096 - len(self.coverage))])
        self.distance = min(self.distance, value.get("distance", 1_000_000))
        retained = self.add(actions, result, generation, event_id=event_id)
        reward = min(16, novelty) + 8 * int(new_family and retained) + 4 * int(improved and retained) + 2 * int(new_structure and retained)
        return {"reward": reward, "retained": retained, "family_id": family_id,
                "new_family": new_family, "coverage_novelty": novelty, "distance_improved": improved}

    def choose(self, rng, explore=False, priors=None):
        families = sorted({e["family_id"] for e in self.records.values()})
        weights = [max(1, 1 + 16 // (1 + self.family_uses.get(f, 0)) +
                       8 * self.family_rewards.get(f, 0) // (1 + self.family_uses.get(f, 0))) *
                   (priors or {}).get(f, 1) for f in families]
        family = rng.choice(families) if explore else rng.choices(families, weights=weights, k=1)[0]
        entries = [r for r in self.records.values() if r["family_id"] == family]
        chosen = rng.choice(entries)
        self.family_uses[family] = self.family_uses.get(family, 0) + 1
        return copy.deepcopy(chosen)

    def credit(self, family, reward):
        if any(e["family_id"] == family for e in self.records.values()):
            self.family_rewards[family] = self.family_rewards.get(family, 0) + reward

    def summaries(self):
        result = []
        for family in sorted({e["family_id"] for e in self.records.values()}):
            entries = [e for e in self.records.values() if e["family_id"] == family]
            result.append({"family_id": family, "descriptor": entries[0]["family"],
                           "cases": [e["case_id"] for e in entries],
                           "selections": self.family_uses.get(family, 0), "reward": self.family_rewards.get(family, 0)})
        return result


class Scheduler:
    def __init__(self, operators):
        self.operators = operators
        self.stats = {}

    def context(self, family):
        return family if family in self.stats or len(self.stats) < 256 else "overflow"

    def choose(self, rng, family, priors, explore=False):
        context = self.context(family)
        stats = self.stats.get(context, {})
        weights = [priors[op] * (1 + (16 * stats.get(op, {}).get("reward", 0) //
                   (1 + stats.get(op, {}).get("attempts", 0)))) for op in self.operators]
        return rng.choice(self.operators) if explore else rng.choices(self.operators, weights=weights, k=1)[0]

    def record(self, family, operator, reward, count_attempt=True, newly_productive=False):
        context = self.context(family)
        stats = self.stats.setdefault(context, {}).setdefault(operator, {"attempts": 0, "productive": 0, "reward": 0})
        stats["attempts"] += int(count_attempt)
        stats["productive"] += int(count_attempt and reward > 0 or newly_productive)
        stats["reward"] += reward
