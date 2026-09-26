# A3 — module map and the laws each module serves

Status: **v1 implemented and law-tested**, storage-agnostic, importable with no Django,
neomodel or Neo4j driver present (`tests/agent_neo/a3/test_import_boundary.py`). Every law in
`laws.py` — including the lifecycle contracts — is executable: the lifecycle ones run against
the reference interpreter in `reference.py`, which is `ensure` written from the blocks alone
over an in-memory store. Not yet bound to the graph interpreter
(`agent_neo.analytical_product`); the binding contract is stated at the end. Charter and
rationale: [`AGENTS.md`](AGENTS.md).

## What an author writes

```python
term = Lower(Slice(
    Roll(Roll(Classify(Lift(Ensure(Ask('zone_temp', 'site', 'zone', None, 'hourly'), 'temp'), 'mean'),
                        'shift', 'shift_of_hour'),
              Dimension.SUBJECT, 'floor', 'space'),
         Dimension.PERIOD, 'daily', 'time'),
    (('shift', 'day'),)))

shape(term, env)      # Shape | Refuse — decided from coordinates alone, no payload read
evaluate(term, env)   # Carrier | Refuse — the same plan, over values
```

"Mean zone temperature per floor, per day, day shift only; refuse if any zone is missing."
Every name in the term — the operator, the lattices, the classifier — is bound by the
`Env`; the algebra ships none of them. `shape` and `evaluate` agree by construction
(`LAW_SHAPE_SOUND`): every refusal is decided before a value is touched. A recipe that serves
a whole family writes its leaves *relative* to the ask being served
(`Ensure(AskFrom('zone_temp', 'zones_of'), 'temp')`); what it reads stays static.

## Modules

| Module | Holds | Laws it serves |
| --- | --- | --- |
| `carrier.py` | `Coordinate` (hashable; two rollable `Dimension`s plus classifications), `Absent` | the address space everything else keys on |
| `algebra.py` | `Carrier` (cells, `expected`, operator tag, `lowered_from`, provenance as identities, gaps, family); primitives `lift` `roll` `restrict` `rekey` `map` `join` `lower`; derived `slice` `shift` `classify` `scale` `diff`; boundary `rank`; `plan_roll` (shared with the shape checker); every primitive absorbs a `Refuse` | REFUSE_ABSORBS · TAG_GUARDS_FOLD · REPORTED_REENTRY · ROLL_REQUIRES_PARTITION · ROLL_REFUSES_DOUBLE_COUNT · EMPTY_FOLD_IS_ABSENT · ROLL_PATH_INDEPENDENT · ROLL_DIMENSION_COMMUTE · SLICE_COMMUTES_WITH_ROLL · CLASSIFY_IS_KEY · JOIN_INNER_CELLS_UNION_EXPECTED · REKEY_IS_A_FUNCTOR · DERIVED_BY_EXPANSION · SCALE_ROLL_COMMUTE · PROVENANCE_IS_LEAVES |
| `operators.py` | `Operator` = `lift`/`combine`/`lower` + `exact` + `partial_ok` + `value_type` + storage `columns` with `encode`/`decode`; `Sum` `Min` `Max` (exact), `Count`, `Mean` `WeightedMean` `Proportion` (one `RatioAccumulator`, stored as report + denominator), `Percentile` (needs a `Sketch`); `OperatorRegistry` that runs the laws over samples at registration | COMBINE_ASSOCIATIVE · COMBINE_COMMUTATIVE · LOWER_LIFT_SINGLETON · EXACT_OPERATOR · HOLISTIC_NEEDS_ACCUMULATOR · PARTIAL_IS_ESTIMATE |
| `lattice.py` | `Lattice` protocol (`up`/`down` over `(level, key)`, multi-valued), `MappingLattice` | LATTICE_CONSISTENT; the slot every roll consults |
| `product.py` | `Layer`, `LifecycleStatus` (the interpreter re-exports these), `Concept` (family + opaque revision + `Field` roles and columns + optional term; dependencies derived from the term or declared without one), `Identity` + `KeyScheme` (with `canonical`), `Instance` + `LineageRef`, `Ask`, `Refuse`/`RefuseReason`, `servable` | KEY_DEVERSIONED · DEPENDS_ON_DERIVED · SERVABLE · the FieldRole half of REPORTED_REENTRY |
| `gates.py` | `is_mature` / `maturity_gate`, `freshness_gate`, `lineage_gate` (from the instance's facts and its lineage refs), `gate` → `GateOutcome` | GATE_ORDER · LINEAGE_FROM_FACTS |
| `bridge.py` | `Resolver` and `Store` protocols; `carrier_from_instances` (expected = the ask, canonical under the scheme; tag from the field's role; accumulators decoded from their columns); `instances_from_carrier` (refuses a tag/role mismatch; accumulators encoded into their columns; lineage = the stored leaves, whatever families) | BRIDGE_DENOMINATOR · BRIDGE_ROUND_TRIP · PROVENANCE_IS_LEAVES · KEY_DEVERSIONED |
| `term.py` | term nodes (`Ensure` with a literal `Ask` or an `AskFrom`, `Lift` `Roll` `Restrict` `Slice` `Classify` `Shift` `Rekey` `Map` `Join` `Lower`), `Env` (operators, lattices, functions, classifiers, scheme, `now`, maturity, the ask being served, `ensure`), `shape`, `evaluate`, `leaves`, `leaf_ask`, `products_read`, `check_layers` | SHAPE_SOUND · DEPENDS_ON_DERIVED · LAYERS · ENSURE_RECURSIVE |
| `ops.py` | the three contracts only a store can fulfil: `Ensure` `Retire` `Invalidate` | ENSURE_IDEMPOTENT · RETIRE_NOT_MUTATE · REDO_DERIVED |
| `reference.py` | `MemoryStore` (Store + Retire + Invalidate over histories; `fetch` refreshes lineage facts) and `ReferenceInterpreter` (`ensure` from the blocks: ensure leaves, gate, evaluate over what was served, bridge, retire) | ENSURE_IDEMPOTENT · ENSURE_RECURSIVE · RETIRE_NOT_MUTATE · REDO_DERIVED — executable; the conformance target for any binding |
| `laws.py` | the 35 laws, each with hypotheses and the block it forces | — |

## The decisions, in one place

- **Coverage is derived, not stored.** `Carrier.expected` is the denominator; it enters at the
  bridge from the ask and is transformed by every primitive. `missing = expected − cells`.
- **A roll's denominator is intrinsic.** For a parent it is `lattice.down(parent)`, less the
  candidates a bound classifier says would not carry the parent's classification value. It
  depends on the parent, the lattice and the classifiers — never on what else the carrier
  holds — so slicing before or after a roll gives the same answer, a child no ask mentioned
  is a gap, and a classification that varies along the rolled dimension refuses without its
  classifier rather than guessing. A coordinate carrying a value its classifier would not
  assign folds into nothing. A child with two parents refuses under every policy.
- **Two tags, and a re-entry rule, make bad folds unwritable.** `operator` says the cells are
  accumulators of one operator; `lowered_from` is the ordered history of operators whose
  reports these values are. `roll` needs the first. `lift` refuses a value into an operator
  already in its history unless that operator is *exact* (its report is its accumulator): a
  sum of stored sums is a sum, rolled further; a mean of means, a count of counts, a p95 of
  p95s are unconstructible; a mean of daily totals is a mean whose unit of analysis is the
  day. Whether the mean was computed a moment ago or read back from a `REPORTED` field, the
  rule is the same.
- **Provenance is identities.** Every derived cell knows the stored leaves it came from as
  `(family, coordinate)`, so lineage across a join of two families is exact, and `classify`,
  `rekey` and `shift` keep pointing at the leaves as stored. Gaps name the finest coordinates
  known to be missing, so rolling a rolled carrier equals rolling the leaves — in cells,
  expected, provenance and gaps.
- **The algebra is closed over `Carrier | Refuse`.** Every primitive returns an input
  `Refuse` unchanged; a composition never checks between steps.
- **Join keeps one-sided gaps.** Cells are inner, but the expected set is the union.
- **The resolver classifies the expected set.** A classified ask (`day=weekday`) expects only
  the coordinates that carry that classification; the same classifiers a roll consults decide
  which those are.
- **Operators are commutative semigroups, exact or not, with a storage shape.** No unit: the
  empty fold is `Absent`, and a report the operator cannot define lowers to an absent cell.
  `exact` replaces Gray's classification (recoverable from `exact` and `mergeable`).
  `columns`/`encode`/`decode` are how a stored `(average, count)` re-enters as a mean. The
  registry runs the laws over samples before it accepts an operator.
- **Family in the key, revision on the instance.** Retiring a recipe changes no key. Under an
  interpreter's `KeyScheme` the key is the interpreter's, byte for byte, and coordinates that
  differ only by explicit neutral classifications are one identity — the bridge canonicalizes.
  A concept's revision is the store's recipe key verbatim.
- **Three gates, three questions, one order.** Maturity refuses; absence and lineage
  recompute before age is considered; freshness recomputes; then serve. `now` is injected.
  Lineage is decided from facts on the instance and its `LineageRef`s. An instance whose
  recipe nobody looked up (`producing=None`) is recomputed, not served.
- **Reading a leaf is ensuring it.** An interpreter ensures a recipe's leaves before it gates
  the recipe's own instances, then evaluates over exactly what was served; a refused upstream
  is a missing cell, never a stale value read around the gate. Invalidation therefore reaches
  every dependent through refreshed facts; a cascade of flags is an optimisation.
- **Terms name things; environments bind them.** Nothing in a3 is a policy value.

## Refusals and where they come from

| `RefuseReason` | Produced by |
| --- | --- |
| `ILL_TYPED_ROLL` | `roll` on values; `lift` on accumulators; `lift` of a report into an inexact operator already in its history |
| `NO_MERGEABLE_ACCUMULATOR` | `lift`/`roll` with a holistic operator and no accumulator bound |
| `INCOMPLETE_PARTITION` | `roll` under `REFUSE`; `PARTIAL` with an operator whose `partial_ok` is false; the reference `ensure` when a recipe produced nothing at an asked identity |
| `DOUBLE_COUNTED` | `roll`, under every policy, when a child has more than one parent |
| `UNSUPPORTED_COMPOSITION` | `map`/`join`/`scale`/`rank` on accumulators; `lower` on values; mixed levels; a lattice with no path or an inconsistent one; a mislabelled classified child; re-`classify`; `slice` on a classification the coordinates do not carry; non-injective `rekey`/`shift`; a missing rate; a bridge write whose tag does not match the declared role; a recipe that does not produce the asked coordinate |
| `IMMATURE_WINDOW` | `maturity_gate`; a term's `Roll` along the period when the environment carries `now`, a lag and period ends |
| `LAYER_VIOLATION` | `check_layers` on a concept that reads above its layer |
| `NOT_SERVABLE` | `servable` on a concept that is not a view |
| `NO_RECIPE` | `ensure` of a missing or invalid instance whose concept holds no term |

Programmer misuse — calling a bare `Percentile` directly, lifting a value type the operator
does not take, registering an operator that breaks its own laws, declaring an accumulator
field without its columns — raises `IllegalOperatorUse` / `ValueError` instead.

## What is not in a3, on purpose

- Any policy value: maturity lag, staleness bound, working hours, holiday calendar.
- Any calendar: the period lattice for hourly/daily/weekly/monthly and the anchor formats
  are the interpreter's, bound through `Env.lattices` and `Env.exclusive_end`.
- Any sketch implementation: `Percentile` takes a `Sketch` factory; digests live in domain packs.
- Judgment (`Interpret`) and presentation: a threshold over a metric is a morphism to a
  label lattice with no rewrite laws; charts and tables are a different grammar.
- Storage: `Ensure`, `Retire`, `Invalidate` are contracts the interpreter fulfils;
  `reference.py` shows what fulfilling them looks like.

## Binding the interpreter (`agent_neo.analytical_product`) — the contract

Already done: `ComputedNodeLayer` and `NodeLifecycleStatus` are the a3 enums; a3 keys under
the interpreter's `KeyScheme` are byte-identical to `build_cache_key` (tested against literal
key strings, both carry forms). Scope of that claim: families keyed by `build_cache_key`.
Products keyed another way (range keys on report views, operator rollups with their own slice
order) need a `KeyScheme` of their own or a migration; `AnalyticalProductIdentity` itself is
unchanged and stays the interpreter's public contract — a3's `Identity` is a projection of it.

A binding conforms when `tests/agent_neo/a3/test_reference.py` passes with its `Store`,
`Resolver` and `Ensure` in place of the reference ones. Normatively, the binding:

1. **Resolves classifier-consistently.** `resolve(ask with k=v)` is the coordinates of
   `resolve(ask without k)` that the classifier bound for `k` admits, stamped `k=v`; the same
   function is bound in `Env.classifiers`. It applies the maturity clamp once, so on this path
   `gate` is called with `exclusive_end=None`.
2. **Fills the policy slots.** `Request → Ask` sets `max_staleness` from the freshness policy
   and `maturity_lag` from the maturity minutes; `None` never crosses on the interpreter path.
3. **Maps nodes to facts.** `needs_redo_since IS NOT NULL → needs_redo`; the producing
   concept's status → `producing` (absent → `None`); each dependency's `(status,
   needs_redo_since, updated)` → a `LineageRef`; `computed_at` as aware UTC — in one batched
   query per cohort, so `lineage_gate` decides what `_is_valid` decides today.
4. **Declares fields.** Every adopted concept declares its `Field` roles and, for
   accumulators, the payload columns (`Mean` → `('average_…', '…_count')`), and its
   dependencies until its recipe is a term.
5. **Ensures leaves first**, then gates, then evaluates over what was served, then persists
   through `instances_from_carrier` (canonical coordinates, encoded columns, lineage keys
   routed to dependency edges).
6. **Builds the subject lattice for the ask's span** and refuses
   `UNSUPPORTED_COMPOSITION` when membership varies over it ("roll SUBJECT per period first").
7. **Preserves its public surface**: the `ValueError` on an emptied range; no `Refuse` value
   leaks out of `AbstractAnalyticalComputedProduct.get()`; `_is_valid` and its helpers stay as
   thin adapters with unchanged signatures.

## Client patterns — learned by writing a recipe against the reference interpreter

- **`OnMissing.REFUSE` refuses the plan; `OnMissing.ABSENT` refuses the identity.** In a recipe that
  serves a family (one term, many subjects), a gap under one subject must not refuse the others:
  use `ABSENT` on the rolls and let `ensure` return the per-identity `Refuse(INCOMPLETE_PARTITION)`
  with the finest gap named. `REFUSE` is for a plan that is meaningless when any part is missing.
- **Slice the asked classification right after `Classify`.** Otherwise the plan also builds the
  sibling slices (`run=off`) and a gap there refuses or absents parents nobody asked for.
- **A classifier is defined at every level it will be consulted at.** A roll to the day asks the
  classifier about day coordinates; "on if any hour under it is on" is the usual shape.
- **A coordinate function that needs the served subject has no way to see it.** Broadcasting a
  site-level series onto the asked plant (`rekey` site → plant) needs the plant; today that takes
  an escape hatch (a context variable set around `ensure`). See the open item below.
- **A leaf's refusal is not chained into its parent's.** The parent's refusal names the missing
  leaf coordinate; asking the leaf's family directly names the finest gap. Chaining is an open item.

## Open after v1 — decided when a consumer needs them, not before

- **Ask-aware coordinate functions.** `Env.functions` entries for `Rekey`/`Map`/`Restrict`/
  `Classify` cannot see `Env.ask`; a broadcast of a site-level series onto the served subject
  needs either that (a function marked as taking the ask first) or a broadcast join. Found by the
  R-COP exercise (kWh per cooling-degree-hour per plant).
- **Chained refusals.** `ensure` drops leaf refusals when it builds the parent's carrier; carrying
  them in the parent refusal's context would make one ask sufficient to see the root cause.

- **Broadcast join** with a coarser or timeless carrier (usage divided by a floor area, a rate
  by a class): `rekey` is injective so it cannot broadcast; `scale(Mapping)` is the interim.
- **Rolling a classification to `all`** (day + night = all) as a third rollable dimension with
  its own lattice; no v1 law needs it.
- **Versioned instances per slot vs in-place refresh** — the known divergence below.
- **Every recipe as a term** (diffable recipes, sub-term-precise invalidation) vs declared
  dependencies for adopted concepts; decided by binding the first real family.
- **A lattice hook for stability over a span** vs the binding's lattice factory alone (v1 puts
  it in the binding, contract item 6).
- **Sketch bindings** (t-digest, KLL) and the tolerance form of `LAW_COMBINE_ASSOCIATIVE`.
- **Explain** rendered from the term and provenance vs the interpreter's graph walk; the term
  language makes it possible, nothing in v1 requires it.
- **A pinned-recipe slot on `Ask`** (the interpreter's concept selection) — add or retire when
  replay is bound.
- **Whether `Coverage.complete` on an empty carrier should ever be false** for primitives other
  than `slice` (a `restrict` that matches nothing is a legitimate plan).

**Known divergence.** `LAW_RETIRE_NOT_MUTATE` says a recompute mints a successor and flips
the prior to `RETIRED`. The interpreter's `cache_key` carries a unique index and its bulk
upsert `MERGE`s on it, so a recompute at the same identity refreshes the node in place. The
law is the contract; the interpreter does not yet meet it. Resolving it is a data-model
decision (versioned instances per slot, or an explicit statement that instances are
refreshed in place and the law applies to concepts only) that belongs to the interpreter.
