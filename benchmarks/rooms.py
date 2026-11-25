"""Four doors and an alarm. Each door is closed, open or locked; the alarm is armed or not.

--bug: disarming while doors A and B are locked, C is open and D is closed leaves the
alarm log inconsistent. Every component phase is easy to reach alone; only the
combination fails. --states reports the full state after every action.
"""
import json
import sys

DOORS = "ABCD"
MOVES = {"open": ("closed", "open"), "close": ("open", "closed"),
         "lock": ("closed", "locked"), "unlock": ("locked", "closed")}


def execute(actions, buggy, states_wanted):
    doors, armed, history, states, coverage = dict.fromkeys(DOORS, "closed"), False, [], [], set()
    for step, action in enumerate(actions):
        op = action["op"]
        if op in MOVES:
            door = action["door"]
            before, after = MOVES[op]
            accepted = doors[door] == before and not (armed and op == "open")
            if accepted:
                doors[door] = after
        else:
            accepted = armed != (op == "arm")
            if buggy and op == "disarm" and armed and (doors["A"], doors["B"], doors["C"], doors["D"]) == \
                    ("locked", "locked", "open", "closed"):
                return reply("fail", history, coverage, states, states_wanted, doors, armed,
                             {"id": "alarm-log", "message": f"inconsistent alarm log at step {step}"})
            if accepted:
                armed = op == "arm"
        coverage.update(f"{d}:{doors[d]}" for d in DOORS)
        coverage.add("alarm:" + ("armed" if armed else "off"))
        history.append([accepted, dict(doors), armed])
        states.append(state(doors, armed))
    return reply("pass", history, coverage, states, states_wanted, doors, armed)


def state(doors, armed):
    return ",".join(doors[d] for d in DOORS) + (",armed" if armed else ",off")


def reply(status, history, coverage, states, states_wanted, doors, armed, failure=None):
    value = {"schema": "evofuzz/observation/1", "status": status, "observation": history,
             "coverage": sorted(coverage), "features": {"family": "armed" if armed else "off"}}
    if failure:
        value["failure"] = failure
        states.append("failed")
    if states_wanted:
        value["states"] = states
    return value


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(json.dumps(execute(request["actions"], "--bug" in sys.argv, "--states" in sys.argv)))
