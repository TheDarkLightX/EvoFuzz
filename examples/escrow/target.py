"""A tiny process target. --bug and --auth-bug are deliberately faulty variants."""
import json
import sys


def execute(actions):
    balance, paid, refunded = 1, 0, 0
    history, coverage = [], set()
    for step, action in enumerate(actions):
        event, authorized = action["op"], action["authorized"]
        accepted = False
        if authorized or "--auth-bug" in sys.argv:
            if balance == 1:
                balance = 0
                if event == "pay":
                    paid = 1
                else:
                    refunded = 1
                accepted = True
            elif "--bug" in sys.argv and event == "refund" and paid and not refunded:
                refunded, accepted = 1, True
        coverage.add(event + (":accepted" if accepted else ":rejected"))
        history.append({"accepted": accepted, "balance": balance, "paid": paid, "refunded": refunded})
        failure = "conservation" if balance + paid + refunded != 1 else (
            "authorization" if accepted and not authorized else None)
        if failure:
            return {"schema": "evofuzz/observation/1", "status": "fail", "coverage": sorted(coverage),
                    "distance": 0, "failure": {"id": failure, "message": f"violated after step {step}"},
                    "observation": history}
    return {"schema": "evofuzz/observation/1", "status": "pass", "coverage": sorted(coverage),
            "distance": 1 if paid and not refunded else 2, "observation": history}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(execute(request["actions"])))
