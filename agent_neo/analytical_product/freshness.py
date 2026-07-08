"""Serving-side time-freshness policy for the unified ``.get(request)`` path.

Time-freshness answers a **serving** question for the caller's enquiry period:

    Should I return this stored computed graph node instance, or obtain a newer one
    that is more appropriate for the time period being asked about?

It is **not** ``needs_redo`` (lineage / upstream / design-node currency requires recompute)
and **not** maturity (may an open-ended window include an in-progress period?).

Enforced in :mod:`agent_neo.analytical_product.abstract` via :class:`ComputeRequest.freshness` /
``_is_age_fresh``.
"""


from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import LiteralString


__all__: tuple[LiteralString, ...] = (
    'FreshnessPolicy',
    'DEFAULT_FRESHNESS_POLICY',
)


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """How long a stored instance may be served before a newer one is preferred.

    ``max_staleness`` bounds how old ``computed_at`` may be while the stored instance
    is still considered an appropriate answer for the caller's enquiry. When age exceeds
    this limit, the ensure path obtains a newer instance — not because lineage flagged
    ``needs_redo``, but because the cached answer is no longer time-appropriate for
    what is being asked about.

    ``None`` disables the age gate entirely. Lineage ``needs_redo`` and input-drift
    checks are separate gates and may still apply.

    Distinct from **maturity** (whether an open-ended window may include an in-progress
    period) and from **needs_redo** (lineage/dependency invalidation — a recomputation
    trigger, not a time-appropriateness judgement).
    """

    max_staleness: timedelta | None = None


#: Default when callers omit an explicit policy: prefer a newer instance if the stored
#: one was computed more than one hour ago. This is a time-appropriateness threshold only;
#: lineage ``needs_redo`` is an unrelated invalidation mechanism.
DEFAULT_FRESHNESS_POLICY: FreshnessPolicy = FreshnessPolicy(max_staleness=timedelta(hours=1))
