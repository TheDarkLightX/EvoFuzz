"""Combination lock: press 3 1 4 1 5 in order, then open. A wrong key restarts progress.

--bug lets the lock open without the owner's authorization once the code is entered.
--states reports the lock's state after every action for state-graph exploration.
"""
import json
import sys

CODE = (3, 1, 4, 1, 5)


def execute(actions, buggy, states_wanted):
    progress, reached, history, states = 0, 0, [], []
    for step, action in enumerate(actions):
        if action["op"] == "press":
            key = action["key"]
            progress = progress + 1 if progress < len(CODE) and key == CODE[progress] else int(key == CODE[0])
        else:
            opened = progress == len(CODE) and (buggy or action["authorized"])
            if opened and not action["authorized"]:
                return reply("fail", history, reached, states, states_wanted,
                             {"id": "unauthorized-open", "message": f"opened without authority at step {step}"})
            progress = 0
        reached = max(reached, progress)
        history.append(progress)
        states.append(f"progress:{progress}")
    return reply("pass", history, reached, states, states_wanted)


def reply(status, history, reached, states, states_wanted, failure=None):
    value = {"schema": "evofuzz/observation/1", "status": status, "observation": history,
             "coverage": [f"stage:{k}" for k in range(reached + 1)],
             "distance": len(CODE) - reached, "features": {"family": f"stage-{reached}"}}
    if failure:
        value["failure"] = failure
        states.append("failed")
    if states_wanted:
        value["states"] = states
    return value


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(execute(request["actions"], "--bug" in sys.argv, "--states" in sys.argv)))
