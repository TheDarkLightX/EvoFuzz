"""User-owned search contracts and declared-input fingerprints."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import sys

from . import __version__, protocol as p
from .domain import Domain

DEFAULTS = {"max_actions": 32, "max_corpus": 64, "timeout_ms": 2000,
            "output_bytes": 65_536, "confirmations": 2, "shrink_budget": 100,
            "proposer_interval": 50, "proposer_timeout_ms": 30_000}
BOUNDS = {"max_actions": (1, 128), "max_corpus": (1, 128), "timeout_ms": (10, 60_000),
          "output_bytes": (1024, 262_144), "confirmations": (2, 5),
          "shrink_budget": (0, 1000), "proposer_interval": (1, 10_000),
          "proposer_timeout_ms": (10, 120_000)}


def command(value, root):
    p.require(type(value) is list and 0 < len(value) <= 32, "command must be a bounded argv list")
    p.require(all(type(x) is str and 0 < len(x) <= 4096 and "\0" not in x for x in value),
              "invalid command argument")
    result = [sys.executable if x == "{python}" else x for x in value]
    executable = result[0]
    if "/" in executable or "\\" in executable:
        path = (root / executable).absolute()
    else:
        found = shutil.which(executable)
        p.require(found is not None, "executable unavailable: " + executable)
        path = Path(found).absolute()
    p.require(path.is_file(), "executable not a file")
    result[0] = str(path)
    return result


def file_hash(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass
class Config:
    path: Path
    data: dict
    limits: dict
    commands: dict
    domain: Domain | None = None
    archive: dict | None = None

    @property
    def root(self):
        return self.path.parent

    @property
    def vocabulary(self):
        return self.data["vocabulary"]

    @property
    def operators(self):
        return self.domain.operators if self.domain else p.OPERATORS

    def fingerprint(self):
        files = {name: file_hash((self.root / name).resolve()) for name in self.data["bindings"]}
        executables = {name: file_hash(Path(cmd[0])) for name, cmd in self.commands.items()}
        return {"schema": "evofuzz/bindings/1", "config_sha256": file_hash(self.path),
                "files": files, "executables": executables,
                "tool_sources": {path.name: file_hash(path) for path in sorted(Path(__file__).parent.glob("*.py"))},
                "commands": self.commands, "tool_version": __version__}


def load(path):
    path = Path(path).resolve()
    data = p.read(path)
    p.keys(data, {"schema", "objective", "command", "oracle", "bindings", "vocabulary",
                  "seeds", "limits", "proposer", "mutants", "domain", "archive"},
           {"schema", "objective", "command", "bindings", "vocabulary", "seeds"})
    p.require(data["schema"] == "evofuzz/target/1", "wrong target schema")
    p.require(type(data["objective"]) is str and 0 < len(data["objective"]) <= 4096, "invalid objective")
    vocabulary = data["vocabulary"]
    p.require(type(vocabulary) is list and 0 < len(vocabulary) <= 128, "vocabulary limit/type")
    p.require(len({p.canonical(x) for x in vocabulary}) == len(vocabulary), "duplicate vocabulary action")
    p.require(len(p.canonical(vocabulary)) <= 16_384, "vocabulary byte limit")
    p.require(type(data["bindings"]) is list and 0 < len(data["bindings"]) <= 128, "bindings limit/type")
    p.require(all(type(x) is str and 0 < len(x) <= 4096 for x in data["bindings"]), "invalid binding")
    p.require(len(set(data["bindings"])) == len(data["bindings"]), "duplicate binding")
    p.require(type(data.get("limits", {})) is dict, "limits must be an object")
    limits = DEFAULTS | data.get("limits", {})
    p.require(limits.keys() == DEFAULTS.keys(), "unknown limits")
    for name, value in limits.items():
        p.integer(value, *BOUNDS[name], name)
    p.require(type(data["seeds"]) is list and 0 < len(data["seeds"]) <= 128, "seed limit/type")
    domain = Domain(vocabulary, data.get("domain"))
    p.require(len(domain.setup) <= limits["max_actions"], "setup exceeds action limit")
    p.require(all(len(b["actions"]) + len(domain.setup) <= limits["max_actions"] for b in domain.blocks),
              "block cannot fit with setup")
    for seed in data["seeds"]:
        p.case(seed, vocabulary, limits["max_actions"], domain)
    settings = data.get("archive", {})
    p.keys(settings, {"features", "per_family", "exploration_percent"}, set())
    settings = {"features": ["family"], "per_family": min(2, limits["max_corpus"]),
                "exploration_percent": 20} | settings
    p.integer(settings["per_family"], 1, min(4, limits["max_corpus"]), "representatives per family")
    p.integer(settings["exploration_percent"], 1, 100, "exploration percentage")
    names = settings["features"]
    p.require(type(names) is list and 1 <= len(names) <= 4 and
              all(type(n) is str and 0 < len(n) <= 128 for n in names), "archive feature limit/type")
    p.require(len(set(names)) == len(names), "duplicate archive feature")
    commands = {"target": command(data["command"], path.parent)}
    for name in ("oracle", "proposer"):
        if name in data:
            commands[name] = command(data[name], path.parent)
    mutants = data.get("mutants", [])
    p.require(type(mutants) is list and len(mutants) <= 16, "mutant limit/type")
    for item in mutants:
        p.keys(item, {"id", "command"}, {"id", "command"})
        p.require(type(item["id"]) is str and 0 < len(item["id"]) <= 128, "invalid mutant ID")
        name = "mutant:" + item["id"]
        p.require(name not in commands, "duplicate mutant ID")
        commands[name] = command(item["command"], path.parent)
    result = Config(path, data, limits, commands, domain, settings)
    result.fingerprint()  # Refuse missing declared inputs before search starts.
    return result
