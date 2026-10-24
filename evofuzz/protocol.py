"""Bounded JSON and strict, model-independent proposal/observation protocols."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MAX_JSON = 1_048_576
OPERATORS = ("insert", "replace", "delete", "duplicate", "swap", "splice", "random")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def _no_number(text):
    raise ValueError("JSON floats and non-finite numbers are unsupported: " + text[:32])


def validate_json(value, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    require(depth <= 20 and count[0] <= 600_000, "JSON nesting/node limit")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        require(value.bit_length() <= 64, "JSON integer exceeds 64 bits")
    elif type(value) is str:
        require(len(value) <= 16_384, "JSON string too long")
    elif type(value) is list:
        for item in value:
            validate_json(item, depth + 1, count)
    elif type(value) is dict:
        for key, item in value.items():
            require(type(key) is str and len(key) <= 256, "invalid JSON object key")
            validate_json(item, depth + 1, count)
    else:
        raise ValueError("unsupported JSON value")


def loads(data, limit=MAX_JSON):
    if isinstance(data, str):
        data = data.encode("utf-8")
    require(len(data) <= limit, "JSON byte limit")
    try:
        result = json.loads(data, object_pairs_hook=_pairs, parse_float=_no_number,
                            parse_constant=_no_number)
        validate_json(result)
        return result
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid/deep JSON") from exc


def canonical(value):
    validate_json(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path):
    with Path(path).open("rb") as stream:
        return loads(stream.read(MAX_JSON + 1))


def write(path, value):
    # All artifacts are bounded JSON values, including the aggregate summaries.
    data = canonical(value)
    require(len(data.encode("utf-8")) <= MAX_JSON, "artifact JSON byte limit")
    Path(path).write_text(data + "\n", encoding="utf-8")


def keys(value, allowed, required):
    require(type(value) is dict, "expected JSON object")
    require(set(required) <= value.keys() <= set(allowed), "missing or unknown fields")


def integer(value, low, high, name):
    require(type(value) is int and low <= value <= high, "invalid " + name)
    return value


def case(actions, vocabulary, max_actions):
    require(type(actions) is list and len(actions) <= max_actions, "case length/type limit")
    known = {canonical(action) for action in vocabulary}
    require(all(canonical(action) in known for action in actions), "action outside vocabulary")
    require(len(canonical(actions)) <= 32_768, "case byte limit")
    return loads(canonical(actions))


def observation(value):
    keys(value, {"schema", "status", "coverage", "distance", "observation", "failure"},
         {"schema", "status", "observation"})
    require(value["schema"] == "evofuzz/observation/1", "wrong observation schema")
    require(value["status"] in ("pass", "fail", "invalid"), "wrong observation status")
    coverage = value.get("coverage", [])
    require(type(coverage) is list and len(coverage) <= 128, "coverage limit/type")
    require(all(type(x) is str and 0 < len(x) <= 128 for x in coverage), "invalid coverage label")
    integer(value.get("distance", 1_000_000), 0, 1_000_000, "distance")
    if value["status"] == "fail":
        failure = value.get("failure")
        keys(failure, {"id", "message"}, {"id"})
        require(type(failure["id"]) is str and 0 < len(failure["id"]) <= 128, "invalid failure ID")
        require(type(failure.get("message", "")) is str, "invalid failure message")
    else:
        require("failure" not in value, "nonfailure observation contains failure")
    return value


def proposal(value, request, vocabulary, max_actions):
    keys(value, {"schema", "request_id", "cases", "weights", "hypothesis"},
         {"schema", "request_id", "cases"})
    require(value["schema"] == "evofuzz/proposal/1", "wrong proposal schema")
    require(value["request_id"] == request["request_id"], "stale/wrong proposal request")
    require(type(value["cases"]) is list and len(value["cases"]) <= 16, "proposal case limit/type")
    cases = [case(item, vocabulary, max_actions) for item in value["cases"]]
    weights = value.get("weights", {})
    require(type(weights) is dict and weights.keys() <= set(OPERATORS), "unknown mutation operator")
    for weight in weights.values():
        integer(weight, 1, 100, "mutation weight")
    hypothesis = value.get("hypothesis", "")
    require(type(hypothesis) is str and len(hypothesis) <= 4096, "hypothesis limit/type")
    return cases, weights
