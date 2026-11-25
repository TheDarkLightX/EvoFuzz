"""Bounded payment-domain harness with an explicit refund-after-payment mutant.

--states reports the authoritative account state after every action, for state-graph search.
"""
import json
import sys


def label(accounts):
    return ",".join(f"{k}:{a['balance']}{a['paid']}{a['refunded']}" for k, a in sorted(accounts.items()))


def execute(actions, buggy=False, states_wanted=False):
    accounts = {key: {"balance": 1, "paid": 0, "refunded": 0} for key in ("A", "B")}
    history, coverage, states = [], set(), []
    family = "exploration"
    ids, pays = set(), set()
    for index, action in enumerate(actions):
        op = action["op"]
        accepted = False
        if op == "restart":
            family = "recovery"
            accepted = True  # This model's restart preserves all authoritative state.
        else:
            key, actor, amount = action["id"], action["actor"], action["amount"]
            ids.add(key)
            if actor != "owner":
                family = "authorization"
            elif family != "recovery":
                if op == "refund":
                    family = "reversal"
                elif len(ids) > 1:
                    family = "identity"
                elif key in pays:
                    family = "replay"
            account = accounts[key]
            if actor == "owner" and amount == 1:
                if account["balance"] == 1:
                    account["balance"] = 0
                    account["paid" if op == "pay" else "refunded"] += 1
                    accepted = True
                elif buggy and op == "refund" and account["paid"] and not account["refunded"]:
                    account["refunded"] += 1
                    accepted = True
            if op == "pay":
                pays.add(key)
        coverage.add(op + (":accepted" if accepted else ":rejected"))
        history.append({"accepted": accepted, "accounts": json.loads(json.dumps(accounts))})
        states.append(label(accounts))
        if any(sum(a.values()) != 1 for a in accounts.values()):
            return {"schema": "evofuzz/observation/1", "status": "fail", "observation": history,
                    "coverage": sorted(coverage), "features": {"family": family}, "distance": 0,
                    "failure": {"id": "conservation", "message": f"double payout after step {index}"}} | \
                ({"states": states} if states_wanted else {})
    distance = 1 if any(a["paid"] for a in accounts.values()) else 2
    return {"schema": "evofuzz/observation/1", "status": "pass", "observation": history,
            "coverage": sorted(coverage), "features": {"family": family}, "distance": distance} | \
        ({"states": states} if states_wanted else {})


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin)["actions"], "--bug" in sys.argv, "--states" in sys.argv)))
