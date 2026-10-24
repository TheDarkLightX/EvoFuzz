"""Protocol demonstration, NOT an LLM or evidence of model-guidance effectiveness."""
import json
import sys

request = json.load(sys.stdin)
print(json.dumps({"schema": "evofuzz/proposal/1", "request_id": request["request_id"],
                  "hypothesis": "Try an authorized payment followed by an authorized refund.",
                  "cases": [[{"op": "pay", "authorized": True}, {"op": "refund", "authorized": True}]],
                  "weights": {"duplicate": 3, "insert": 3}}))
