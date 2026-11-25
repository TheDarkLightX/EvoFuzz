# State-graph exploration

This is the contract for optional, target-reported state labels. Labels steer search; the
target's properties and oracles still decide every verdict. Nothing here is a safety claim.

## Why

Mutation re-executes sequences whose prefixes the campaign has already explored. In a
stateful target, many different sequences reach the same state, and the number of sequences
grows as |actions|ⁿ while the number of reachable states often does not. When the target
says which state each action reached, EvoFuzz can treat sequences that reach the same label
as interchangeable *for search*. It then tries each (state, action) pair instead of
rediscovering it by chance.

## Protocol

An observation may include `states`, an array with one label per **executed** action:
`states[i]` names the target state after action `i`. A target that stops at a failing step
reports labels up to and including that step. Labels are strings of 1–128 characters; the
name `<start>` is reserved for the state before any action. More labels than actions is a
protocol error. A label should be a deterministic function of the authoritative state and
should omit clocks, counters and identifiers that do not affect future behavior.

## What the graph keeps

- the shortest known action sequence to each label, shortest-first and then canonical;
- every observed transition `(label, action) → label`, with the sequence that witnessed it;
- the declared actions each label has tried;
- labels where execution stopped (a failure, or fewer labels than actions). They are
  terminal: the target ran nothing after them, so they are never expanded;
- for each action, how often its observed transitions changed the label.

It holds at most 4096 labels and 16384 transitions. Past either bound it stops growing and
reports `truncated`.

## The frontier operator

Enable it with `"archive": {"state_frontier": true}`. A frontier case is the shortest known
sequence to a label, then one declared action that label has not tried, then a random tail of
up to `frontier_tail` actions (default 16, within `max_actions`).
- **Choosing the label.** Labels are weighted by 1/(1 + times chosen), as in count-based
  exploration.
- **Weighting actions.** Both the untried action and the tail actions are weighted toward
  actions that usually change the label. In many targets most actions are rejected
  self-loops, and a walk that idles explores nothing.
- **Parameter domains.** With parameter domains, candidate actions are sampled from the
  domain; "untried" then means untried among the samples.

After the initial seeds, `frontier_percent` of non-exploration attempts (default 80) that do
not consume a queued case use the frontier while one exists. The rest use the learned scheduler, which may
also pick `frontier` as an operator. Uniform exploration attempts are unaffected. The
scheduler's reward adds up to 16 for new labels and up to 8 for new transitions, for any
operator.

## Shorter witnesses

When a confirmed failure reports labels, EvoFuzz first tries a shortcut. It takes the
shortest known sequence to the label before the failing step, then the failing action. The
shortcut is skipped if it violates the declared domain or required setup prefix. It
replaces the original only if repeated execution reproduces the same failure
signature. Delta debugging then continues from it. The finding records the shortcut under
`minimization.state_shortcut`.

## When a label is too coarse

If one `(label, action)` pair is observed with two different successors, the label misses a
distinction the target makes. The graph records the conflict with both witnessing sequences
and stops expanding or shortcutting through that label. Conflicts appear in `summary.json`
and `states.json`. They say the harness's label is incomplete; they are not findings. A label
can also be incomplete without any observed conflict, for example when a hidden variable
changes only a property check.

## Closed depth

For a finite vocabulary with no parameter domain, no setup prefix, no conflicts and no
truncation, `closed_depth` is the largest `d` with this property: every label first reached
in fewer than `d` actions has tried every declared action. `fully_expanded` means every
reached label has. Both describe exploration of the *reported* labels. They support no safety
conclusion: the labels may be incomplete, the target nondeterministic, and properties may
depend on more than the label. `summary.exhaustive` stays `false`.

## Artifacts

- `states.json` (`evofuzz/state-graph/1`) holds the summary, conflicts, and the shortest known
  sequences for the shallowest labels. The complete serialized file, including conflict
  witnesses and metadata, fits within a 900 KB budget. `conflicts_omitted` and
  `shortest_omitted` count retained graph records left out of the artifact; the graph
  summary still reports its full counts. Conflict evidence is budgeted first.
- `summary.json` gains `state_graph`.
- `lineage.jsonl` frontier events name the expanded label in `frontier_state` and have no
  genetic parents.
- Adaptive proposal requests include the graph summary in `feedback.state_graph`, and may
  weight the `frontier` operator.

## Limits

- Labels are the target's claim. They are not verified equivalence, and a wrong label can hide
  a bug from the frontier; mutation and uniform exploration continue regardless.
- Frontier cases still execute their whole prefix, because every case runs in a fresh process.
- On targets with very many reachable labels, the frontier is one search strategy among others;
  its benefit is measured, not assumed. See [benchmarks](../benchmarks/README.md).
