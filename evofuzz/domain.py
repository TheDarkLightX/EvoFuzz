"""Bounded user-declared action domains; no executable model-generated code."""
from __future__ import annotations

import copy

from . import protocol as p


class Domain:
    def __init__(self, vocabulary, data=None):
        self.vocabulary = copy.deepcopy(vocabulary)
        self.data = copy.deepcopy({} if data is None else data)
        p.keys(self.data, {"parameters", "identity_fields", "blocks", "setup"}, set())
        self.parameters = self.data.get("parameters", {})
        p.require(type(self.parameters) is dict and len(self.parameters) <= 16, "parameter domain limit/type")
        for name, spec in self.parameters.items():
            p.require(name != "op" and 0 < len(name) <= 128, "invalid parameter field")
            p.require(any(type(a) is dict and name in a for a in vocabulary), "parameter absent from vocabulary")
            if type(spec) is dict and set(spec) == {"values"}:
                values = spec["values"]
                p.require(type(values) is list and 1 <= len(values) <= 64, "enum domain limit/type")
                p.require(all(self.scalar(x) for x in values), "enum values must be bounded scalars")
                p.require(len({p.canonical(x) for x in values}) == len(values), "duplicate enum value")
            else:
                p.keys(spec, {"min", "max"}, {"min", "max"})
                p.integer(spec["min"], -(2**63), 2**63 - 1, "parameter minimum")
                p.integer(spec["max"], spec["min"], min(2**63 - 1, spec["min"] + 1_000_000_000), "parameter maximum")
        self.identity_fields = self.data.get("identity_fields", [])
        p.require(type(self.identity_fields) is list and len(self.identity_fields) <= 8, "identity field limit/type")
        p.require(all(type(k) is str and k in self.parameters and "values" in self.parameters[k]
                      for k in self.identity_fields), "identity fields require enum domains")
        p.require(len(set(self.identity_fields)) == len(self.identity_fields), "duplicate identity field")
        self.setup = self.data.get("setup", [])
        p.require(type(self.setup) is list and len(self.setup) <= 16, "setup limit/type")
        p.require(all(self.accepts(a) for a in self.setup), "setup outside action domain")
        self.blocks = self.data.get("blocks", [])
        p.require(type(self.blocks) is list and len(self.blocks) <= 16, "block limit/type")
        names = set()
        for block in self.blocks:
            p.keys(block, {"name", "actions"}, {"name", "actions"})
            p.require(type(block["name"]) is str and 0 < len(block["name"]) <= 128, "invalid block name")
            p.require(block["name"] not in names, "duplicate block name")
            names.add(block["name"])
            p.require(type(block["actions"]) is list and 1 <= len(block["actions"]) <= 16, "block action limit/type")
            p.require(all(self.accepts(a) for a in block["actions"]), "block outside action domain")
        p.require(all(self.accepts(a) for a in vocabulary), "vocabulary prototype outside parameter domain")
        p.require(len(p.canonical(self.data)) <= 16_384, "domain byte limit")

    @staticmethod
    def scalar(value):
        return value is None or type(value) in (bool, int) or type(value) is str and len(value) <= 128

    def member(self, field, value):
        spec = self.parameters[field]
        if "values" in spec:
            return p.canonical(value) in {p.canonical(x) for x in spec["values"]}
        return type(value) is int and spec["min"] <= value <= spec["max"]

    def accepts(self, action):
        for prototype in self.vocabulary:
            if p.canonical(action) == p.canonical(prototype):
                if type(action) is not dict or all(self.member(k, v) for k, v in action.items() if k in self.parameters):
                    return True
            if type(action) is not dict or type(prototype) is not dict or action.keys() != prototype.keys():
                continue
            if all(self.member(k, v) if k in self.parameters else p.canonical(v) == p.canonical(prototype[k])
                   for k, v in action.items()):
                return True
        return False

    def validate(self, actions):
        p.require(all(self.accepts(a) for a in actions), "action outside declared domain")
        p.require(len(actions) >= len(self.setup) and p.canonical(actions[:len(self.setup)]) == p.canonical(self.setup),
                  "required setup prefix changed or missing")

    @property
    def operators(self):
        return p.OPERATORS + (("parameter",) if self.parameters else ()) + (
            ("rebind",) if self.identity_fields else ()) + (("block",) if self.blocks else ())

    def sample_value(self, rng, name):
        spec = self.parameters[name]
        if "values" in spec:
            return copy.deepcopy(rng.choice(spec["values"]))
        low, high = spec["min"], spec["max"]
        boundaries = sorted({low, high, min(high, low + 1), max(low, high - 1), max(low, min(high, 0))})
        return rng.choice(boundaries) if rng.randrange(2) == 0 else rng.randint(low, high)

    def sample(self, rng):
        action = copy.deepcopy(rng.choice(self.vocabulary))
        if type(action) is dict:
            for name in sorted(action.keys() & self.parameters.keys()):
                action[name] = self.sample_value(rng, name)
        return action

    def parameter(self, rng, actions):
        candidates = [(i, k) for i, a in enumerate(actions) if i >= len(self.setup) and type(a) is dict
                      for k in sorted(a.keys() & self.parameters.keys())]
        if candidates:
            i, k = rng.choice(candidates)
            actions[i][k] = self.sample_value(rng, k)

    def rebind(self, rng, actions):
        choices = [(i, k) for i, a in enumerate(actions) if i >= len(self.setup) and type(a) is dict
                   for k in self.identity_fields if k in a]
        if choices:
            i, key = rng.choice(choices)
            old, new = p.canonical(actions[i][key]), self.sample_value(rng, key)
            indices = [j for j, a in enumerate(actions) if j >= len(self.setup) and type(a) is dict
                       and key in a and p.canonical(a[key]) == old] if rng.randrange(2) else [i]
            for j in indices:
                actions[j][key] = copy.deepcopy(new)
