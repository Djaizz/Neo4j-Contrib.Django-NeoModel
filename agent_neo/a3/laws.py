"""The laws, stated with their hypotheses, each naming the block it forces.

A law is not documentation. It is the reason a block exists: strike the law and the block it
forces becomes unearned. Every law here has an executable test in ``tests/agent_neo/a3/``; the
interpreter contracts at the end run against :mod:`agent_neo.a3.reference`, and a
storage-bound interpreter is conformant when the same tests pass against its store.
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
not op.mergeable  ⇒  lift(·, op) and roll of accumulators tagged op are Refuse(NO_MERGEABLE_ACCUMULATOR), and the
registry refuses to register op. mergeable is False only for a Percentile with no sketch bound; an exact
multiset is a lawful (unbounded) accumulator.
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

LAW_REPORTED_REENTRY = """
lower appends name(op) to lowered_from; restrict, rekey, map, scale and join carry it (join: ordered union);
no primitive clears it. lift(c, op) on a carrier with lowered_from ≠ () is Refuse(ILL_TYPED_ROLL) iff
name(op) ∈ lowered_from and not op.exact; otherwise it succeeds and keeps the history.
So: a mean of means, a count of counts, a p95 of p95s are unconstructible; a sum of daily sums is the sum
(exact: rolling further); a mean of daily sums is a mean whose unit of analysis is the day. Forces: exact,
lift_refusal.
"""

LAW_EXACT_OPERATOR = """
op.exact  ⇔  lift(lower(a)) == a for every accumulator a. True for Sum, Min, Max; false for Count and every
ratio and quantile. OperatorRegistry.register(name, op, samples=...) runs LAW_COMBINE_ASSOCIATIVE,
LAW_COMBINE_COMMUTATIVE, this law and the encode/decode round trip over the samples and raises
IllegalOperatorUse on a violation: a law an operator breaks is caught at registration, not in a fold.
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
A child with more than one parent along the rolled dimension is Refuse(DOUBLE_COUNTED) under every OnMissing
policy: a lattice that is not a partition is not missing data, and no policy about gaps may fold it.
Forces: set-valued Lattice.up.
"""

LAW_EMPTY_FOLD_IS_ABSENT = """
A parent none of whose children are present is absent, never an operator's unit (there is none); a report
the operator cannot define (a ratio over nothing) lowers to an absent cell, still expected, so still missing.
Zero is a value; absence is the lack of one.
"""

LAW_ROLL_PATH_INDEPENDENT = """
    roll(roll(c, D → M1), M1 → M2) == roll(c, D → M2)
in cells, expected, provenance and gaps, for every operator and OnMissing policy, with or without missing
leaves: gaps name the finest coordinates known to be missing under a parent, and a roll of a rolled
carrier propagates them rather than recording the intermediate level. This is the rewrite that lets a
stored daily accumulator stand in for the hours beneath it.
"""

LAW_REFUSE_ABSORBS = """
For every primitive p and Refuse r:  p(r, ...) == r  and  p(..., r) == r  (the left refusal when both).
The algebra is closed over Carrier | Refuse; the first refusal in a composition is its result, and no
step checks for one. Forces: _absorbing on every primitive; evaluate has no isinstance between steps.
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
whenever a classifier for k is bound to the roll (the denominator is intrinsic: down(parent) admitted by
the classifier, whatever else the carrier holds). Without one, a classification that varies along the
rolled dimension makes both orders refuse INCOMPLETE_PARTITION rather than one of them guess.
"""

LAW_CLASSIFY_IS_KEY = """
After classify(c, k, f) — rekey with a computed classification — rolling groups by k as by any coordinate
component, and with f bound as the classifier for k a parent (k=v) expects exactly the children f assigns v:
a subject whose k differs is not that parent's gap. A child carrying k=v that f would not assign v is
Refuse(UNSUPPORTED_COMPOSITION): a mislabelled coordinate folds into nothing. Before classify, slice(c, k=v)
is a Refuse: the absence of a key is not a value of it. Forces: classifiers on plan_roll, slice_refusal.
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
Concept.depends_on == products_read(concept.term) when the concept holds a term — a declaration that
disagrees is a ValueError, never a second source of truth. A concept adopted without a term declares its
dependencies, so check_layers applies to it too; binding its recipe as a term replaces the declaration.
"""

LAW_LAYERS = """
check_layers(concept) is Refuse(LAYER_VIOLATION) iff some family the term reads sits above
concept.layer. Forces: Layer.may_depend_on inside the algebra.
"""


# ---------------------------------------------------------------------------
# Bridge and provenance — force: Carrier.provenance, Instance.lineage, the bridge
# ---------------------------------------------------------------------------

LAW_BRIDGE_DENOMINATOR = """
carrier_from_instances(expected, present).missing == coords(expected) − coords(present); a payload holding
None for the field, or for any of an accumulator's columns, is an absent cell. An instance outside expected,
or two at one coordinate, raises: a broken store, not a data condition.
"""

LAW_BRIDGE_ROUND_TRIP = """
For every field role r and a carrier c whose tag matches r:
    carrier_from_instances(ids, instances_from_carrier(c, spec=r), spec=r) == c   (cells up to rounding)
— accumulators through the operator's storage columns and encode/decode, reports as REPORTED with the
operator's class name, plain values as LEAF. A carrier whose tag does not match the declared role is
Refuse(UNSUPPORTED_COMPOSITION) on the way in: the declaration the algebra will consult later may not lie.
"""

LAW_PROVENANCE_IS_LEAVES = """
sources(parent) == ∪ sources(present children); a leaf's source is itself under the family it was
read from; classify, rekey and shift keep pointing at the stored leaves they moved; join unites both
sides' sources; instances_from_carrier(...).lineage == the sources' cache keys, whatever families
they came from. Sources are identities, not coordinates: after a join a coordinate names nothing.
"""


# ---------------------------------------------------------------------------
# Identity — force: Concept.family vs Concept.revision, KeyScheme
# ---------------------------------------------------------------------------

LAW_KEY_DEVERSIONED = """
Identity.cache_key depends on the product family and the coordinate only; minting or retiring a
Concept revision changes no key. Under an interpreter's KeyScheme the key is byte-identical to
the one that interpreter writes — including its all-or-none rule for classification suffixes —
and two coordinates that differ only by explicit neutral classifications are one identity: the
bridge canonicalizes both the expected set and the instances before it matches them.
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
# Interpreter contracts — executable against agent_neo.a3.reference; a binding conforms when they pass against its store
# ---------------------------------------------------------------------------

LAW_ENSURE_IDEMPOTENT = """
ensure(ask) twice with unchanged inputs and a SERVE verdict returns the same instances and mints nothing:
the store's history at every identity is unchanged by the second call.
"""

LAW_ENSURE_RECURSIVE = """
Reading a leaf is ensuring it: evaluate(Ensure(ask)) under a bound Env.ensure produces or refuses the
upstream by the same path that serves it, so ensure(view) leaves every product under the view current.
A recipe is relative to the ask it serves — its leaves derive their asks from Env.ask — and still
declares statically what it reads (products_read is defined on AskFrom as on Ask).
"""

LAW_RETIRE_NOT_MUTATE = """
retire(prior, successor) persists successor as current and flips prior to RETIRED; prior's payload is
never rewritten; there is no supersession edge. (The reference interpreter's unique cache_key index
currently makes it refresh in place instead — a known divergence recorded in SKETCH.md.)
"""

LAW_REDO_DERIVED = """
An instance is recomputed iff gate() says RECOMPUTE. Ask carries no field that forces it. Invalidating
an upstream makes every dependent recompute on its next ensure even when nothing flagged the dependent:
the gate reads the upstream's flag through the refreshed lineage refs (cascade is an optimisation).
"""


__all__ = tuple(sorted(name for name in globals() if name.startswith('LAW_')))
