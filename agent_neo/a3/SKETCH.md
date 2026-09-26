# A3 — module map and the laws each module serves

Status: **v1 implemented and law-tested**, storage-agnostic, importable with no Django,
neomodel or Neo4j driver present (`tests/agent_neo/a3/test_import_boundary.py`). Not yet
bound to the graph interpreter (`agent_neo.analytical_product`); the bindings it needs are
listed at the end. Charter and rationale: [`AGENTS.md`](AGENTS.md).

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
(`LAW_SHAPE_SOUND`): every refusal is decided before a value is touched.

## Modules

| Module | Holds | Laws it serves |
| --- | --- | --- |
| `carrier.py` | `Coordinate` (hashable; two rollable `Dimension`s plus classifications), `Absent` | the address space everything else keys on |
| `algebra.py` | `Carrier` (cells, `expected`, operator tag, `lowered_from`, provenance, gaps); primitives `lift` `relift` `roll` `restrict` `classify` `rekey` `map` `join` `lower`; derived `slice` `shift` `scale` `diff`; boundary `rank`; `plan_roll` (shared with the shape checker) | TAG_GUARDS_FOLD · REPORTED_NEVER_LIFTED · DISTRIBUTIVE_RELIFT · ROLL_REQUIRES_PARTITION · ROLL_REFUSES_DOUBLE_COUNT · EMPTY_FOLD_IS_ABSENT · ROLL_DIMENSION_COMMUTE · SLICE_COMMUTES_WITH_ROLL · CLASSIFY_IS_KEY · JOIN_INNER_CELLS_UNION_EXPECTED · REKEY_IS_A_FUNCTOR · DERIVED_BY_EXPANSION · SCALE_ROLL_COMMUTE · PROVENANCE_IS_LEAVES |
| `operators.py` | `Operator` = `lift`/`combine`/`lower` + `kind` (Gray) + `partial_ok`; `Sum` `Count` `Min` `Max` (distributive), `Mean` `WeightedMean` `Proportion` (algebraic, one `RatioAccumulator`), `Percentile` (holistic, needs a `Sketch`); `OperatorRegistry` | COMBINE_ASSOCIATIVE · COMBINE_COMMUTATIVE · LOWER_LIFT_SINGLETON · HOLISTIC_NEEDS_ACCUMULATOR · PARTIAL_IS_ESTIMATE |
| `lattice.py` | `Lattice` protocol (`up`/`down` over `(level, key)`, multi-valued), `MappingLattice` | LATTICE_CONSISTENT; the slot every roll consults |
| `product.py` | `Layer`, `LifecycleStatus` (the interpreter re-exports these), `Concept` (family + revision + `Field` roles + optional term), `Identity` + `KeyScheme` (with `canonical`), `Instance` + `LineageRef`, `Ask`, `Refuse`/`RefuseReason`, `servable` | KEY_DEVERSIONED · DEPENDS_ON_DERIVED · SERVABLE · the FieldRole half of REPORTED_NEVER_LIFTED |
| `gates.py` | `is_mature` / `maturity_gate`, `freshness_gate`, `lineage_gate` (from the instance's facts and its lineage refs), `gate` → `GateOutcome` | GATE_ORDER · LINEAGE_FROM_FACTS |
| `bridge.py` | `Resolver` and `Store` protocols; `carrier_from_instances` (expected = the ask; tag from the field's role); `instances_from_carrier` (lineage = leaves) | BRIDGE_DENOMINATOR · PROVENANCE_IS_LEAVES |
| `term.py` | term nodes (`Ensure` `Lift` `Relift` `Roll` `Restrict` `Slice` `Classify` `Shift` `Rekey` `Map` `Join` `Lower`), `Env` (operators, lattices, functions, classifiers, `now`, maturity), `shape`, `evaluate`, `products_read`, `check_layers` | SHAPE_SOUND · DEPENDS_ON_DERIVED · LAYERS |
| `ops.py` | the three contracts only a store can fulfil: `Ensure` `Retire` `Invalidate` | ENSURE_IDEMPOTENT · RETIRE_NOT_MUTATE · REDO_DERIVED (interpreter-tested) |
| `laws.py` | the 31 laws, each with hypotheses and the block it forces | — |

## The decisions, in one place

- **Coverage is derived, not stored.** `Carrier.expected` is the denominator; it enters at the
  bridge from the ask and is transformed by every primitive. `missing = expected − cells`.
  A roll's denominator for a parent is `lattice.down(parent)`, so a child no ask mentioned is
  a gap — minus children the carrier knows under a sibling classification, minus children a
  bound classifier says would not carry the parent's classification.
- **Two tags make bad folds unwritable.** `operator` says the cells are accumulators of one
  operator; `lowered_from` says the values are some operator's reported output. `roll` needs
  the first; `lift` refuses the second. Whether the mean was computed a moment ago or read
  back from a `REPORTED` field, it never re-enters a fold. The one lawful way back is
  `relift`, for a *distributive* operator's own output — a sum of stored sums is a sum — and
  that is the only place Gray's classification is consulted.
- **Join keeps one-sided gaps.** Cells are inner, but the expected set is the union: a
  coordinate one side lacks is a gap of the join, not a coordinate that stops mattering.
- **The resolver classifies the expected set.** A classified ask (`day=weekday`) expects only
  the coordinates that carry that classification; the same classifiers a roll consults decide
  which those are. The ask's classification is a slice on the world, not a stamp on every
  coordinate.
- **Operators are commutative semigroups with a Gray kind.** No unit: the empty fold is
  `Absent`. `partial_ok` says whether a fold over present children is an estimate (mean,
  min, quantile) or an undercount (sum, count).
- **Family in the key, revision on the instance.** Retiring a recipe changes no key. Under an
  interpreter's `KeyScheme` the key is the interpreter's, byte for byte.
- **Three gates, three questions, one order.** Maturity refuses; absence and lineage
  recompute before age is considered; freshness recomputes; then serve. `now` is injected.
  Lineage is decided from facts on the instance and its `LineageRef`s — its own status and
  flag, whether anything records its recipe, the recipe's status, each input's status, flag and
  last change — never from a bit someone else derived.
- **Terms name things; environments bind them.** Nothing in a3 is a policy value.

## Refusals and where they come from

| `RefuseReason` | Produced by |
| --- | --- |
| `ILL_TYPED_ROLL` | `roll` on values; `lift` on accumulators or on lowered values; `relift` of anything but a distributive operator's own output |
| `NO_MERGEABLE_ACCUMULATOR` | `lift`/`roll` with a holistic operator and no accumulator bound |
| `INCOMPLETE_PARTITION` | `roll` under `REFUSE`; `PARTIAL` with an operator whose `partial_ok` is false |
| `DOUBLE_COUNTED` | `roll` under `REFUSE` when a child has more than one parent |
| `UNSUPPORTED_COMPOSITION` | `map`/`join`/`scale`/`rank` on accumulators; `lower` on values; mixed levels; a lattice with no path; re-`classify`; non-injective `rekey`/`shift`; a missing rate |
| `IMMATURE_WINDOW` | `maturity_gate`; a term's `Roll` along the period when the environment carries `now`, a lag and period ends |
| `LAYER_VIOLATION` | `check_layers` on a concept whose term reads above its layer |
| `NOT_SERVABLE` | `servable` on a concept that is not a view |

Programmer misuse — lowering an empty accumulator, calling a bare `Percentile` directly,
lifting a value type the operator does not take — raises `IllegalOperatorUse` instead. A plan
never reaches the first two; the third is the one failure a payload alone reveals.

## What is not in a3, on purpose

- Any policy value: maturity lag, staleness bound, working hours, holiday calendar.
- Any calendar: the period lattice for hourly/daily/weekly/monthly and the anchor formats
  are the interpreter's, bound through `Env.lattices` and `Env.exclusive_end`.
- Any sketch implementation: `Percentile` takes a `Sketch` factory; digests live in domain packs.
- Judgment (`Interpret`) and presentation: a threshold over a metric is a morphism to a
  label lattice with no rewrite laws; charts and tables are a different grammar.
- Storage: `Ensure`, `Retire`, `Invalidate`, `Project`, `Explain` are contracts the
  interpreter fulfils.

## Binding the interpreter (`agent_neo.analytical_product`) — what remains

Already done: `ComputedNodeLayer` and `NodeLifecycleStatus` are the a3 enums; a3 keys under
the interpreter's `KeyScheme` are byte-identical to `build_cache_key` (tested). Scope of that
claim: families keyed by `build_cache_key`. Products keyed another way (range keys on report
views, operator rollups with their own slice order) need a `KeyScheme` of their own or a
migration; `AnalyticalProductIdentity` itself is unchanged and stays the interpreter's public
contract — a3's `Identity` is a projection of it.

Remaining, in order of value:

1. A `Resolver` over `AnalyticalProductRequest.resolve_identities` (window enumeration,
   maturity clamp, and subject enumeration for `subject_key=None`).
2. A `Store` over the current-instance probe and fetch, mapping node properties to
   `Instance` (`computed_at`, `lifecycle_status`, `needs_redo_since` → `needs_redo`, the
   producing concept's status → `producing`) and its dependency edges to `LineageRef`s
   (status, flag, `updated`), so `lineage_gate` decides what `_is_valid` decides today.
3. A calendar `Lattice` for the period dimension, and `exclusive_end`, over `util.datetime`.
4. `Concept.fields` declarations for existing product classes, so stored accumulators can be
   rolled further and stored reports cannot be re-lifted.
5. Rewriting `_is_valid` on the three gate functions (behaviour-preserving).

**Known divergence.** `LAW_RETIRE_NOT_MUTATE` says a recompute mints a successor and flips
the prior to `RETIRED`. The interpreter's `cache_key` carries a unique index and its bulk
upsert `MERGE`s on it, so a recompute at the same identity refreshes the node in place. The
law is the contract; the interpreter does not yet meet it. Resolving it is a data-model
decision (versioned instances per slot, or an explicit statement that instances are
refreshed in place and the law applies to concepts only) that belongs to the interpreter.
