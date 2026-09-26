"""The laws, stated with their hypotheses, each naming the block it forces.

A law is not documentation. It is the reason a block exists: strike the law and the block it
forces becomes unearned. Every law here has an executable test in ``tests/agent_neo/a3/``,
except the three interpreter contracts at the end, which say so.
"""


from __future__ import annotations

# ---------------------------------------------------------------------------
# Operators — force: Operator.combine's preconditions, AggregateKind, partial_ok, the registry
# ---------------------------------------------------------------------------

LAW_COMBINE_ASSOCIATIVE = """
For every operator and accumulators a, b, c in its domain (floats up to rounding; NaN excluded):
    combine(a, combine(b, c)) == combine(combine(a, b), c)
"""

LAW_COMBINE_COMMUTATIVE = """
For every operator and accumulators a, b:  combine(a, b) == combine(b, a)
A precondition, not a declaration: a fold runs over an unordered set of children.
"""

LAW_LOWER_LIFT_SINGLETON = """
For Sum, Min, Max, Mean and an accumulator-bound Percentile, and any value v:  lower(lift(v)) == v
"""

LAW_HOLISTIC_NEEDS_ACCUMULATOR = """
kind == HOLISTIC and not mergeable  ⇒  lift(·, op) is Refuse(NO_MERGEABLE_ACCUMULATOR) and
OperatorRegistry.register(op) raises. An exact multiset is a lawful (unbounded) accumulator.
"""

LAW_PARTIAL_IS_ESTIMATE = """
roll(on_missing=PARTIAL) with an operator whose partial_ok is False is Refuse(INCOMPLETE_PARTITION):
a sum or a count over some of the children is an undercount, not an estimate.
"""


# ---------------------------------------------------------------------------
# Tags — force: Carrier.operator, Carrier.lowered_from, FieldRole
# ---------------------------------------------------------------------------

LAW_TAG_GUARDS_FOLD = """
roll(values) is Refuse(ILL_TYPED_ROLL); lift(accumulators) is Refuse(ILL_TYPED_ROLL);
map / join / scale / rank over accumulators are Refuse(UNSUPPORTED_COMPOSITION).
"""

LAW_REPORTED_NEVER_LIFTED = """
A carrier with lowered_from ≠ () — the output of lower, or a REPORTED field read from the store —
is Refuse(ILL_TYPED_ROLL) under lift, and join propagates lowered_from to its result.
Once lowered, a value never re-enters a fold through lift: mean-of-means and p95-of-p95s cannot be
written, whether the mean was computed a moment ago or persisted last month.
"""

LAW_DISTRIBUTIVE_RELIFT = """
relift(c, op) re-enters op's OWN reported values as its accumulators iff c.lowered_from == (op,) and
op.kind is DISTRIBUTIVE — for such an operator the accumulator is the value, so a sum of stored sums
is a sum. Anything else is Refuse(ILL_TYPED_ROLL). This is the one place AggregateKind is consulted,
and it is what earns it. Forces: AggregateKind, relift.
"""


# ---------------------------------------------------------------------------
# Roll and coverage — force: Carrier.expected, Lattice.up/down, Coverage, gaps, plan_roll
# ---------------------------------------------------------------------------

LAW_LATTICE_CONSISTENT = """
For every lattice and every pair of levels:  c ∈ down(p, L_child)  ⟺  p ∈ up(c, L_parent).
plan_roll relies on it; MappingLattice guarantees it by construction.
"""

LAW_ROLL_REQUIRES_PARTITION = """
Rolling to a parent P whose expected children are not all present:
    REFUSE  -> Refuse(INCOMPLETE_PARTITION) naming P and the missing children;
    ABSENT  -> P absent from cells, P in expected, gaps[P] == the missing children;
    PARTIAL -> P folded from the present children (partial_ok operators only), gaps[P] recorded.
P's expected children are lattice.down(P) — so a child no ask ever mentioned is a gap — minus
children the carrier knows under another classification (they belong to P's sibling there).
"""

LAW_ROLL_REFUSES_DOUBLE_COUNT = """
If any child has |lattice.up(child)| > 1 at the target level: REFUSE is Refuse(DOUBLE_COUNTED);
ABSENT and PARTIAL leave every parent that child touches absent.
"""

LAW_EMPTY_FOLD_IS_ABSENT = """
A parent some of whose children were expected but none of which are present is in expected and
absent from cells, for every operator: no identity element stands in for missing data, so no
operator needs a unit. Conversely a roll invents no parent the ask never implied:
expected(roll(c)) == {up(child) for child in c.expected}.
"""

LAW_ROLL_DIMENSION_COMMUTE = """
For lattices that are INDEPENDENT — subject membership does not vary over the carrier's period span,
so the leaf set under (S, P) is down(S) × down(P):
    roll(SUBJECT→L1, roll(PERIOD→L2, c)) == roll(PERIOD→L2, roll(SUBJECT→L1, c))
in cells, expected and provenance, under every on_missing policy (gaps may name different
intermediate levels). Partition-ness is not needed: with a missing leaf or a double-counted child both
orders refuse, or go absent, identically. Forces: Coordinate.moved, Dimension.
"""

LAW_SLICE_COMMUTES_WITH_ROLL = """
    roll(slice(c, k=v)) == slice(roll(c), k=v)
when the classification k is constant across each parent's children (a shift assigned from
the hour, rolled along the subject). When k varies across a parent's children — a shift that
differs by subject — roll first and slice after; roll knows a sibling classification is not a
gap, slice has already thrown it away.
"""

LAW_CLASSIFY_IS_KEY = """
After classify(c, k, f), rolling groups by k as by any coordinate component: a subject whose k
differs from the parent's is not that parent's gap. Forces: classify, the known-keys rule in plan_roll.
"""


# ---------------------------------------------------------------------------
# Join, shift and derivation — force: join, shift; force NOTHING for slice/scale/diff/rank
# ---------------------------------------------------------------------------

LAW_JOIN_INNER_CELLS_UNION_EXPECTED = """
cells(join(a, b)) == {c: (a[c], b[c]) for c present in both}; expected == a.expected ∪ b.expected, so a
coordinate one side expected and the other lacks is a gap of the join, never a coordinate that stops
mattering; sources(c) == a.sources(c) ∪ b.sources(c). Values only.
"""

LAW_REKEY_IS_A_FUNCTOR = """
rekey(c, f) for f injective on c.expected relabels cells, expected and gaps, keeps the operator tag
(accumulators move as freely as values) and keeps provenance pointing at the original leaves.
shift(c, dim, g) == rekey(c, λx. x.moved(dim, level, g(key))); diff(a, shift(b, PERIOD, next)) at anchor
t equals a[t] − b[prev(t)], cell for cell.
"""

LAW_DERIVED_BY_EXPANSION = """
slice(c, k=v) == restrict(c, λx. x.k == v);  shift == rekey along one dimension;  scale(c, r) == map(c, v ↦ v·r);
diff(a, b) == map(join(a, b), (x, y) ↦ x − y).  They add no expressive power.
"""

LAW_SCALE_ROLL_COMMUTE = """
For Sum, and a rate r constant over each parent's children:
    lower(roll(lift(scale(c, r)))) == scale(lower(roll(lift(c))), r)
When r varies within a parent's children the right-hand side is wrong and the left is the
only lawful order. (This is the whole of the "linear map" side condition; no flag encodes it.)
"""


# ---------------------------------------------------------------------------
# Terms — force: term nodes, Env, shape, Concept.term, Layer.may_depend_on
# ---------------------------------------------------------------------------

LAW_SHAPE_SOUND = """
For every term t and environment e:
    shape(t, e) is a Refuse  ⟺  evaluate(t, e) is a Refuse, with the same reason;
    otherwise shape(t, e).expected == evaluate(t, e).expected and shape(t, e).present == cells(evaluate(t, e)).
Every refusal is decidable without a payload. The one failure a payload alone reveals — an operator fed a
value type it does not take — is a plan-authoring error and raises IllegalOperatorUse, never a wrong number.
Forces: plan_roll, lift_refusal, roll_refusal being shared.
"""

LAW_SERVABLE = """
servable(concept) is Refuse(NOT_SERVABLE) iff concept.layer is not VIEW: only views cross the serving
boundary; every other layer exists to support them. Forces: Layer.is_served.
"""

LAW_DEPENDS_ON_DERIVED = """
Concept.depends_on == products_read(concept.term): the families its Ensure leaves read. Never declared.
"""

LAW_LAYERS = """
check_layers(concept) is Refuse(LAYER_VIOLATION) iff some family the term reads sits above
concept.layer. Forces: Layer.may_depend_on inside the algebra.
"""


# ---------------------------------------------------------------------------
# Bridge and provenance — force: Carrier.provenance, Instance.lineage, the bridge
# ---------------------------------------------------------------------------

LAW_BRIDGE_DENOMINATOR = """
carrier_from_instances(expected, present).missing == coords(expected) − coords(present); a payload
holding None for the field is an absent cell. An instance outside expected, or two at one
coordinate, raises: a broken store, not a data condition.
"""

LAW_PROVENANCE_IS_LEAVES = """
sources(parent) == ∪ sources(present children); a leaf's sources are itself; shift keeps them;
instances_from_carrier(...).lineage == the leaf identities' cache keys.
"""


# ---------------------------------------------------------------------------
# Identity — force: Concept.family vs Concept.revision, KeyScheme
# ---------------------------------------------------------------------------

LAW_KEY_DEVERSIONED = """
Identity.cache_key depends on the product family and the coordinate only; minting or retiring a
Concept revision changes no key. Under an interpreter's KeyScheme the key is byte-identical to
the one that interpreter writes — including its all-or-none rule for classification suffixes.
"""


# ---------------------------------------------------------------------------
# Gates — force: Instance.computed_at, Ask.max_staleness, Ask.maturity_lag, GateOutcome
# ---------------------------------------------------------------------------

LAW_LINEAGE_FROM_FACTS = """
lineage_gate decides from the instance and its LineageRefs alone, in this order:
  instance retired                          -> NOT_CURRENT
  instance flagged                          -> NEEDS_REDO
  producing is None (nothing recorded it)   -> NO_RECIPE
  producing retired                         -> RETIRED_RECIPE
  any ref retired or flagged                -> UPSTREAM_INVALID
  any ref updated after computed_at         -> INPUT_CHANGED   (undecidable, so skipped, when computed_at is unknown)
The interpreter supplies the facts it already fetches; the gate does not trust a bit it did not derive.
"""

LAW_GATE_ORDER = """
gate() decides in this order and stops at the first that applies:
  immature window                 -> REFUSE(IMMATURE_WINDOW)
  no instance                     -> RECOMPUTE(NEEDS_REDO)
  lineage_gate says recompute     -> RECOMPUTE(its reason)
  unknown age, or older than max_staleness -> RECOMPUTE(STALE)
  otherwise                       -> SERVE
A None slot disables its gate. Freshness and lineage are never conflated.
"""


# ---------------------------------------------------------------------------
# Interpreter contracts — stated here, tested by the interpreter
# ---------------------------------------------------------------------------

LAW_ENSURE_IDEMPOTENT = """
ensure(ask) twice with unchanged inputs and a SERVE verdict returns the same instances and mints nothing.
"""

LAW_RETIRE_NOT_MUTATE = """
retire(prior, successor) persists successor as current and flips prior to RETIRED; prior's payload is
never rewritten; there is no supersession edge. (The reference interpreter's unique cache_key index
currently makes it refresh in place instead — a known divergence recorded in SKETCH.md.)
"""

LAW_REDO_DERIVED = """
An instance is recomputed iff gate() says RECOMPUTE. Ask carries no field that forces it.
"""


__all__ = tuple(sorted(name for name in globals() if name.startswith('LAW_')))
