"""Separate test oracle: an escrow can leave funded exactly once, with authority."""
import json
import sys

request = json.load(sys.stdin)
phase = "funded"
history = []
for action in request["actions"]:
    allowed = phase == "funded" and action["authorized"]
    if allowed:
        phase = "paid" if action["op"] == "pay" else "refunded"
    history.append({"accepted": allowed, "balance": int(phase == "funded"),
                    "paid": int(phase == "paid"), "refunded": int(phase == "refunded")})
print(json.dumps({"schema": "evofuzz/observation/1", "status": "pass", "observation": history}))
