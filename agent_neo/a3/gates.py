"""The three gates, kept apart because they answer three different questions.

- **Maturity** — has this period *settled*? Source data lands late; a window is mature only
  once ``lag`` has elapsed past its exclusive end. Asked directly about an immature window,
  the algebra refuses. Resolving an open-ended ask, an interpreter uses the same predicate
  to clamp the window instead — one definition, two uses.
- **Freshness** — is this stored answer still *appropriate* for the question being asked?
  A bound on how old ``computed_at`` may be. Failing it means "obtain a newer instance",
  not "the old one was wrong".
- **Lineage** — must this be *recomputed* regardless of age? Because it is retired or
  flagged, because nothing records — or a retired recipe records — what produced it, because
  something it read is retired or flagged, or because something it read changed after it was
  computed. Each is a fact the store already holds; the gate reads them from the instance and
  its lineage refs rather than trusting a bit someone else derived.

Conflating the last two is the common mistake this module exists to prevent: an instance
can be minutes old and still need redo; it can be lineage-valid and still too old to serve.

Every function takes ``now`` as an argument. The algebra has no clock; the caller does.
"""


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from agent_neo.a3.product import Ask, Instance, LifecycleStatus, Refuse, RefuseReason

__all__ = (
    'GateOutcome',
    'RecomputeReason',
    'Verdict',
    'freshness_gate',
    'gate',
    'is_mature',
    'lineage_gate',
    'maturity_gate',
)


class Verdict(StrEnum):
    SERVE = 'serve'
    RECOMPUTE = 'recompute'
    REFUSE = 'refuse'


class RecomputeReason(StrEnum):
    STALE = 'stale'  # freshness: too old for the enquiry, or of unknown age
    NOT_CURRENT = 'not_current'  # lineage: the instance itself is retired
    NEEDS_REDO = 'needs_redo'  # lineage: the instance is flagged, or absent
    NO_RECIPE = 'no_recipe'  # lineage: nothing records what produced it
    RETIRED_RECIPE = 'retired_recipe'  # lineage: the recipe that produced it is retired
    UPSTREAM_INVALID = 'upstream_invalid'  # lineage: something it read is retired or flagged
    INPUT_CHANGED = 'input_changed'  # lineage: something it read changed after it was computed


@dataclass(frozen=True, slots=True)
class GateOutcome:
    verdict: Verdict
    recompute_reason: RecomputeReason | None = None
    refusal: Refuse | None = None

    @classmethod
    def serve(cls) -> GateOutcome:
        return cls(Verdict.SERVE)

    @classmethod
    def recompute(cls, reason: RecomputeReason) -> GateOutcome:
        return cls(Verdict.RECOMPUTE, recompute_reason=reason)

    @classmethod
    def refuse(cls, refusal: Refuse) -> GateOutcome:
        return cls(Verdict.REFUSE, refusal=refusal)


# ---------------------------------------------------------------------------
# Maturity
# ---------------------------------------------------------------------------


def is_mature(*, exclusive_end: datetime, now: datetime, lag: timedelta | None) -> bool:
    """A period has settled once ``lag`` has elapsed after its exclusive end. ``lag=None``: always."""
    if lag is None:
        return True
    return now >= exclusive_end + lag


def maturity_gate(*, exclusive_end: datetime, now: datetime, lag: timedelta | None) -> Refuse | None:
    if is_mature(exclusive_end=exclusive_end, now=now, lag=lag):
        return None
    return Refuse(
        RefuseReason.IMMATURE_WINDOW,
        f'period ending {exclusive_end.isoformat()} is not mature until {(exclusive_end + lag).isoformat()}',  # type: ignore[operator]
        {'exclusive_end': exclusive_end, 'mature_at': exclusive_end + lag, 'now': now},  # type: ignore[operator]
    )


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def freshness_gate(instance: Instance, *, max_staleness: timedelta | None, now: datetime) -> RecomputeReason | None:
    """``None`` bound disables the gate; otherwise the instance must be of known age and no older than the bound."""
    if max_staleness is None:
        return None
    if instance.computed_at is None or now - instance.computed_at > max_staleness:
        return RecomputeReason.STALE
    return None


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def lineage_gate(instance: Instance) -> RecomputeReason | None:
    """Must this be recomputed regardless of age? Decided from the facts on the instance and
    its lineage refs, in the order the interpreter checks them."""
    if instance.lifecycle is LifecycleStatus.RETIRED:
        return RecomputeReason.NOT_CURRENT
    if instance.needs_redo:
        return RecomputeReason.NEEDS_REDO
    if instance.producing is None:
        return RecomputeReason.NO_RECIPE
    if instance.producing is LifecycleStatus.RETIRED:
        return RecomputeReason.RETIRED_RECIPE
    for ref in instance.lineage:
        if ref.lifecycle is LifecycleStatus.RETIRED or ref.needs_redo:
            return RecomputeReason.UPSTREAM_INVALID
    if instance.computed_at is not None:
        for ref in instance.lineage:
            if ref.updated_at is not None and ref.updated_at > instance.computed_at:
                return RecomputeReason.INPUT_CHANGED
    return None


# ---------------------------------------------------------------------------
# Composition: the ensure path's single decision
# ---------------------------------------------------------------------------


def gate(instance: Instance | None, ask: Ask, *, now: datetime, exclusive_end: datetime | None = None) -> GateOutcome:
    """Decide what the ensure path does with what it found at an identity.

    Order matters and is deliberate: an immature window is refused before anything is
    served or computed; a missing or lineage-invalid instance is recomputed before its age
    is even considered; only a present, lineage-valid instance is judged for freshness.
    """
    if exclusive_end is not None:
        refusal = maturity_gate(exclusive_end=exclusive_end, now=now, lag=ask.maturity_lag)
        if refusal is not None:
            return GateOutcome.refuse(refusal)
    if instance is None:
        return GateOutcome.recompute(RecomputeReason.NEEDS_REDO)
    lineage = lineage_gate(instance)
    if lineage is not None:
        return GateOutcome.recompute(lineage)
    freshness = freshness_gate(instance, max_staleness=ask.max_staleness, now=now)
    if freshness is not None:
        return GateOutcome.recompute(freshness)
    return GateOutcome.serve()
