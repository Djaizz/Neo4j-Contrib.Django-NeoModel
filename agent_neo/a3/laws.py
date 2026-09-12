"""Property-test *intent* for A3 composition laws.

No pytest suite yet — these are named contracts future tests should assert.
When trivial pure helpers fall out of a real Operator implementation, add
``hypothesis`` / unit tests next to them; do not invent a fake suite here.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Roll / Operator monoid laws
# ---------------------------------------------------------------------------

LAW_ROLL_DIMENSION_COMMUTE = """
When Operator.combine is associative and commutative, and d1, d2 are independent
dimensions with Coverage that partitions at each step:

    roll(d1, roll(d2, carrier)) == roll(d2, roll(d1, carrier))

as Carrier equality on lowered values at the shared parent Coordinate.
"""

LAW_COMBINE_ASSOCIATIVE = """
Operator.combine(a, combine(b, c)) == Operator.combine(combine(a, b), c)
for all Accumulators a, b, c in the operator's domain.
"""

LAW_COMBINE_COMMUTATIVE = """
When the op claims reorder safety (Sum, Count, Mean, Min, Max, Proportion):

    Operator.combine(a, b) == Operator.combine(b, a)
"""

LAW_LIFT_LOWER_ROUNDTRIP = """
For operators where lower is a left inverse of lift on singletons:

    lower(lift(v)) == v
"""

LAW_NO_COMBINE_ON_LOWERED = """
Storing lower(acc) then calling combine on those scalars must be rejected
(IllegalOperatorUse or Refuse(NO_MERGEABLE_ACCUMULATOR)) — never silently
produce p95-of-p95 style nonsense.
"""


# ---------------------------------------------------------------------------
# Coverage / partition
# ---------------------------------------------------------------------------

LAW_ROLL_REQUIRES_PARTITION = """
roll(..., into=parent) returns Refuse(INCOMPLETE_PARTITION) unless
Coverage.partitions_parent() is True for the folded children.
"""


# ---------------------------------------------------------------------------
# Slice
# ---------------------------------------------------------------------------

LAW_SLICE_COMMUTES_WITH_MONOID_ROLL = """
For monoid Operator O and classification restriction S that selects a subset of
a partition:

    roll(dim, slice(S, carrier), O) == slice(S_parent, roll(dim, carrier, O))

when S_parent is the induced restriction on the rolled Coordinate.
"""


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------

LAW_SCALE_LINEAR_ONLY = """
scale(carrier, rate) is legal when rate is constant on the window being rolled.
If rate varies over child cells that will later Roll with a non-homomorphism,
return Refuse(NONLINEAR_SCALE_OVER_WINDOW) rather than inventing a wrong total.
"""


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

LAW_ENSURE_IDEMPOTENT = """
ensure(ask) twice with unchanged inputs and passing Gate yields the same
Identity and does not mint a new official Instance (serve existing).
"""

LAW_RETIRE_NOT_MUTATE = """
Updating a product always mints a successor Instance and flips the prior to
LifecycleStatus.RETIRED. Payload fields of the prior node are never rewritten.
"""

LAW_NO_FORCE_REDO = """
Ask has no force_redo / recompute flag. Redo only via Invalidate → needs_redo
and Gate failure on stale / immature windows.
"""


__all__ = (
    'LAW_COMBINE_ASSOCIATIVE',
    'LAW_COMBINE_COMMUTATIVE',
    'LAW_ENSURE_IDEMPOTENT',
    'LAW_LIFT_LOWER_ROUNDTRIP',
    'LAW_NO_COMBINE_ON_LOWERED',
    'LAW_NO_FORCE_REDO',
    'LAW_RETIRE_NOT_MUTATE',
    'LAW_ROLL_DIMENSION_COMMUTE',
    'LAW_ROLL_REQUIRES_PARTITION',
    'LAW_SCALE_LINEAR_ONLY',
    'LAW_SLICE_COMMUTES_WITH_MONOID_ROLL',
)
