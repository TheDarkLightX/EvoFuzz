# Domain-aware evolution

This is the implementation contract for version 0.2.
It extends the initial finite-vocabulary engine without changing the target
oracles' authority. Completion and validation are recorded separately.

## What descendants explore

A seed such as `[pay, pay]` can produce multiple behavioral families: replay,
identity confusion, authorization, reversal and recovery. Each descendant is
one concrete action sequence. Two descendants may belong to the same family;
mutations may also produce identical sequences. Exact duplicates are skipped
and logged. No finite search promises that every child has unique behavior or
that every possible family will be found.

The search language must express the behavior: changing a request identity or
inserting `restart` is possible only when the user declares those parameters
and operations. The model cannot invent executable domain actions or relax the
oracle. A family label is a search descriptor, not evidence of a vulnerability.

## Three implemented changes

1. **Domain-aware variation.** Optional bounded parameter domains extend the
   existing vocabulary prototypes. Enum and integer parameters can change at
   declared fields. Identity rebinding creates shared or distinct references.
   Named action blocks preserve multi-step idioms; an optional fixed setup
   prefix preserves required initialization. Deliberately invalid operational
   sequences remain testable unless the user explicitly excludes them.
2. **Family-preserving retention.** Use declared, target-reported feature fields
   as behavioral family keys. If none are available, use a labelled structural
   fallback. Keep a quality representative and, where capacity permits, a
   structurally different representative per family. Reclaim extra slots before
   evicting an entire family. At capacity, the archive is a bounded selection,
   not a claim to preserve every discovered family forever.
3. **Learn from offspring.** Record attempts and useful offspring for each
   `(parent family, mutation operator)` context. Prefer productive combinations
   using integer scores; preserve a positive, configurable exploration share.
   Parent selection also uses measured offspring productivity. This is online
   scheduling, not training the LLM or learning a sound model of all behavior.

## Configuration additions

`domain.parameters` maps field names to `{"values":[...]}` or
`{"min":0,"max":100}`. Parameters apply only to fields present in a vocabulary
prototype; other keys and constants must match exactly. `op` stays fixed.
`domain.identity_fields` selects enum parameters that can be rebound together.
`domain.blocks` contains named vocabulary-valid sequences. `domain.setup` is an
optional required prefix, checked for seeds and model proposals as well as
mutated cases. All collections and parameter ranges are bounded explicitly.

`archive.features` lists target-reported feature names, such as `family` and
`phase`. `archive.per_family` caps representatives and
`archive.exploration_percent` sets the uniform exploration share. Target
observations may add an advisory scalar `features` object. Missing descriptors
are explicitly marked or use structural fallback, never assumed to prove a
semantic relationship.

LLM requests expose the domain, available operators, bounded family summaries
and operator statistics. Proposals may additionally set positive weights for
family IDs named in that exact request. Commands, limits, vocabulary/domain,
feature definitions and oracles remain fixed by the user configuration.

## Evidence

`lineage.jsonl` records parent case/event IDs, operator, generation, child identity and
whether an attempt was executed, invalid or an exact duplicate. Splicing names
both actual parents. Supplied/model cases have no inferred genetic parentage.
Fresh random generation is also recorded as a restart rather than an inherited
genome. Derivation events have distinct IDs even when their sequence content is
identical.
`archive.json` records retained families and representatives; `learning.json`
records attempts and rewards. These are unsigned search records, not proof
certificates. Existing case logs and replay/finding formats remain usable.

Reward coverage novelty, improved distance within a family, a newly retained
family and independently replayed new failures. Do not reward transport errors
or unconfirmed failures as confirmed bugs. Different structures with identical
current behavior may retain different future mutation neighborhoods.

## Bounded acceptance criteria

- Existing finite-vocabulary targets and tests continue to work.
- Parameters, identities, blocks and setup remain within their declared domain.
- A family is not lost merely because another family adds another representative
  while an extra slot can be reclaimed.
- Structurally different candidates can survive in the same behavioral family.
- Learned scheduling responds to measured offspring productivity and retains
  uniform exploration; model weights cannot disable an operator or expand scope.
- Lineage correctly names parents and duplicate attempts; no uniqueness of
  behavioral families is claimed.
- A domain example starting from a payment seed actually explores replay,
  identity, authorization, reversal and recovery descriptors, retaining several
  families and reproducing its deliberately planted defect.
- Full unit/integration suite, package installation, focused CLI journeys,
  public-doc/link checks and hosted platform checks pass on the final source.

No claim of general bug-finding superiority follows from the example. A future
held-out evaluation must compare equal execution and model-cost budgets against
the initial engine and ablations of archive, domain mutations and learning.
