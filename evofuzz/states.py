"""Advisory state-graph exploration from target-reported state labels.

A target may report a label for its state after every action. Sequences that reach the same
label are then treated as interchangeable *for search*: the graph keeps the shortest known
sequence to each label, every observed transition, and which declared actions each label has
tried. The frontier operator extends the shortest sequence to a label with an action it has
not yet tried, so each transition is executed once instead of being rediscovered by mutation.

Labels are the target's claim, not checked equivalence. Two observations of one transition
with different successors show the label misses a distinction; the graph records both
witnesses and stops using that label for shortcuts. Failures are still decided only by the
target and its oracles, and nothing here is a safety claim.
"""
from __future__ import annotations

import copy

from . import protocol as p

START = "<start>"  # Internal name for the state before any action; never a target label.


class StateGraph:
    def __init__(self, vocabulary, domain=None, max_states=4096, max_transitions=16_384):
        self.vocabulary = [copy.deepcopy(a) for a in vocabulary]
        self.domain = domain
        self.setup = len(domain.setup) if domain else 0
        self.parametric = bool(domain and domain.parameters)
        self.keys = [p.digest(a) for a in self.vocabulary]
        self.max_states, self.max_transitions = max_states, max_transitions
        self.prefix = {START: []}
        self.transitions = {}
        self.tried = {START: set()}
        self.conflicts = []
        self.unreliable = set()
        self.terminal = set()
        self.chosen = {}
        self.effect = {}  # action kind -> [tries, transitions that changed the state]
        self.truncated = False

    @staticmethod
    def label(value):
        p.require(type(value) is str and 0 < len(value) <= 128 and value != START,
                  "state labels are strings of 1-128 characters")
        return value

    def observe(self, actions, states, stopped=False):
        """Record one execution's labels. Returns (new labels, new transitions).

        @p stopped marks an execution that ended early, by failure or otherwise. Its last label
        is then terminal: the target never ran an action after it, so it is not expanded.
        """
        p.require(type(states) is list and len(states) <= len(actions), "more state labels than actions")
        new_states = new_transitions = 0
        before = START
        for index, state in enumerate(states):
            state = self.label(state)
            path = actions[:index + 1]
            known = self.prefix.get(state)
            if known is None:
                if len(self.prefix) < self.max_states:
                    self.prefix[state], self.tried[state] = copy.deepcopy(path), set()
                    new_states += 1
                else:
                    self.truncated = True
            elif (len(path), p.canonical(path)) < (len(known), p.canonical(known)):
                self.prefix[state] = copy.deepcopy(path)
            key = (before, p.digest(actions[index]))
            seen = self.transitions.get(key)
            if seen is None:
                if len(self.transitions) < self.max_transitions:
                    self.transitions[key] = (state, copy.deepcopy(path))
                    self.tried.setdefault(before, set()).add(key[1])
                    new_transitions += 1
                    stats = self.effect.setdefault(self.kind(actions[index]), [0, 0])
                    stats[0] += 1
                    stats[1] += int(state != before)
                else:
                    self.truncated = True
            elif seen[0] != state:
                self.unreliable.add(before)
                if len(self.conflicts) < 16:
                    self.conflicts.append({"state": before, "action": copy.deepcopy(actions[index]),
                                           "successors": [seen[0], state], "witnesses": [seen[1], copy.deepcopy(path)]})
            before = state
        if states and (stopped or len(states) < len(actions)):
            self.terminal.add(states[-1])
        return new_states, new_transitions

    def kind(self, action):
        """Actions share effect statistics by operation when parameters vary, else exactly."""
        if self.parametric and type(action) is dict:
            return p.canonical(action.get("op"))
        return p.digest(action)

    def weight(self, action):
        """Prefer actions that usually change the state: walks then move instead of idling."""
        tries, moved = self.effect.get(self.kind(action), (0, 0))
        return 1 + 16 * (moved + 1) // (tries + 2)

    def step(self, rng):
        candidates = [self.domain.sample(rng) for _ in range(4)] if self.parametric else self.vocabulary
        return copy.deepcopy(rng.choices(candidates, weights=[self.weight(a) for a in candidates], k=1)[0])

    def expandable(self, state):
        return (state not in self.unreliable and state not in self.terminal
                and len(self.prefix[state]) >= self.setup and state in self.tried)

    def untried(self, state, rng, attempts=16):
        if not self.parametric:
            return [a for a, k in zip(self.vocabulary, self.keys) if k not in self.tried[state]]
        found = {}
        for _ in range(attempts):
            action = self.domain.sample(rng)
            key = p.digest(action)
            if key not in self.tried[state]:
                found.setdefault(key, action)
        return list(found.values())

    def plan(self, rng, max_actions, tail=0, policy="rare"):
        """A case that tries an untried action from a known state, or None if there is none.

        Policy "rare" picks a state with weight 1/(1 + times chosen), as count-based exploration
        does; "shallow" prefers the shortest known sequences, as breadth-first search does.
        """
        states = sorted((s for s in self.prefix if self.expandable(s) and len(self.prefix[s]) < max_actions),
                        key=lambda s: (len(self.prefix[s]), s))
        if not self.parametric:
            states = [s for s in states if len(self.tried[s]) < len(self.keys)]
        if not states:
            return None
        if policy == "shallow":
            shallow = [s for s in states if len(self.prefix[s]) == len(self.prefix[states[0]])]
            pool = shallow if rng.randrange(4) else states
            order = rng.sample(pool, len(pool))
        else:
            weights = [1_000_000 // (1 + self.chosen.get(s, 0)) for s in states]
            order = []
            for _ in range(min(8, len(states))):
                order.append(rng.choices(states, weights=weights, k=1)[0])
        for state in order:
            options = self.untried(state, rng)
            if options:
                break
        else:
            return None
        self.chosen[state] = self.chosen.get(state, 0) + 1
        choice = rng.choices(options, weights=[self.weight(a) for a in options], k=1)[0]
        actions = copy.deepcopy(self.prefix[state]) + [copy.deepcopy(choice)]
        room = max_actions - len(actions)
        for _ in range(min(room, rng.randrange(tail + 1))):
            actions.append(self.step(rng))
        return actions, state

    def shortcut(self, actions, states):
        """A shorter case reaching the failing step's prior state by its shortest known sequence."""
        if not states:
            return None
        step = len(states) - 1
        before = START if step == 0 else states[step - 1]
        if before in self.unreliable or before not in self.prefix:
            return None
        candidate = copy.deepcopy(self.prefix[before]) + [copy.deepcopy(actions[step])]
        return candidate if len(candidate) < len(actions) else None

    def closed_depth(self):
        """Largest d such that every label first reached in fewer than d actions tried every action.

        Defined only for a finite declared vocabulary without a setup prefix, with no conflicting
        transitions and no truncation; otherwise None. It describes exploration, not safety.
        """
        if self.parametric or self.setup or self.conflicts or self.truncated:
            return None
        depth, frontier, seen = 0, [START], {START}
        while frontier:
            if any(s not in self.terminal and len(self.tried.get(s, ())) < len(self.keys) for s in frontier):
                return depth
            depth += 1
            successors = []
            for s in frontier:
                for k in ([] if s in self.terminal else self.keys):
                    t = self.transitions[(s, k)][0]
                    if t not in seen and t in self.tried:
                        seen.add(t)
                        successors.append(t)
            frontier = successors
        return depth  # Every reachable label is expanded: depth counts all levels.

    def summary(self):
        expandable = [s for s in self.prefix if self.expandable(s)]
        if not self.parametric:
            expandable = [s for s in expandable if len(self.tried[s]) < len(self.keys)]
        closed = self.closed_depth()
        return {"states": len(self.prefix) - 1, "transitions": len(self.transitions),
                "frontier": len(expandable), "closed_depth": closed,
                "fully_expanded": closed is not None and not expandable,
                "terminal_states": len(self.terminal),
                "conflicts": len(self.conflicts), "unreliable_states": len(self.unreliable),
                "truncated": self.truncated}

    def artifact(self, byte_limit=900_000):
        """Summary, conflicts and the shortest known sequences, shallowest first, within a byte budget."""
        shortest, used = {}, 0
        for state, actions in sorted(self.prefix.items(), key=lambda kv: (len(kv[1]), kv[0])):
            if state == START:
                continue
            size = len(p.canonical(actions)) + len(state) + 8
            if used + size > byte_limit:
                break
            shortest[state], used = actions, used + size
        return {"schema": "evofuzz/state-graph/1", "summary": self.summary(), "conflicts": self.conflicts,
                "shortest": shortest, "shortest_omitted": len(self.prefix) - 1 - len(shortest)}
