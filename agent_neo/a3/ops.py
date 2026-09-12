"""High-level product ops — Protocol contracts for the A3 playground.

Bodies are not implemented. Domain packs and a future interpreter wire these.
No Neo4j / Django imports.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from agent_neo.a3.carrier import Carrier, Coordinate
from agent_neo.a3.operators import Operator
from agent_neo.a3.product import Ask, Identity, Instance, Refuse


__all__ = (
    'Compose',
    'Diff',
    'Ensure',
    'Explain',
    'Gate',
    'Invalidate',
    'Join',
    'Map',
    'Project',
    'Rank',
    'Retire',
    'Roll',
    'Scale',
    'Slice',
    'Warm',
)


class Ensure(Protocol):
    """Idempotent materialize-by-Ask.

    Resolve Ask → Identity (or Identities). For each: if a valid Instance exists
    and Gate passes, serve it; else compute → persist → Retire prior official.
    Never accept a force-redo flag — redo only via Invalidate + Gate.
    """

    def ensure(self, ask: Ask) -> Instance | Refuse:
        ...


class Warm(Protocol):
    """Bulk Ensure over mature windows / subject sets (populate path).

    Same Ensure path; caller supplies a batch of Asks rather than one.
    """

    def warm(self, asks: Sequence[Ask]) -> Sequence[Instance | Refuse]:
        ...


class Roll(Protocol):
    """Fold a Carrier along one dimension with a typed Operator.

    Legal only when children's Coverage partitions the parent coordinate.
    Otherwise return Refuse(INCOMPLETE_PARTITION) or Refuse(ILL_TYPED_ROLL).
    Combining lowered scalars (e.g. p95-of-p95) must be unconstructible when
    the Operator has no mergeable accumulator.
    """

    def roll(
        self,
        carrier: Carrier[Any],
        *,
        along: str,
        into: Coordinate,
        operator: Operator[Any, Any],
    ) -> Carrier[Any] | Refuse:
        ...


class Map(Protocol):
    """Pointwise transform on Carrier cells (no fold)."""

    def map(
        self,
        carrier: Carrier[Any],
        transform: Any,
    ) -> Carrier[Any] | Refuse:
        ...


class Scale(Protocol):
    """qty × rate (or similar linear map).

    Legal when the rate is constant over the roll window (document side
    condition). Nonlinear rate over the window → Refuse(NONLINEAR_SCALE_OVER_WINDOW).
    """

    def scale(
        self,
        carrier: Carrier[Any],
        *,
        rate: float | Mapping[Coordinate, float],
    ) -> Carrier[Any] | Refuse:
        ...


class Slice(Protocol):
    """Restrict by classification dimensions (day/hour/…).

    Index-set restriction; under monoid Roll it commutes with fold over a
    partition of that set.
    """

    def slice(
        self,
        carrier: Carrier[Any],
        *,
        classifications: Mapping[str, str],
    ) -> Carrier[Any] | Refuse:
        ...


class Join(Protocol):
    """Align products on subject / period keys → row Carrier."""

    def join(
        self,
        left: Carrier[Any],
        right: Carrier[Any],
        *,
        on: Sequence[str],
    ) -> Carrier[Any] | Refuse:
        ...


class Diff(Protocol):
    """Compare against a baseline or peer window."""

    def diff(
        self,
        primary: Carrier[Any],
        baseline: Carrier[Any],
    ) -> Carrier[Any] | Refuse:
        ...


class Rank(Protocol):
    """Order carrier rows by score."""

    def rank(
        self,
        carrier: Carrier[Any],
        *,
        by: str,
        descending: bool = True,
    ) -> Carrier[Any] | Refuse:
        ...


class Project(Protocol):
    """Metric Instance → View-shaped payload (serving boundary).

    Only Projected Views cross the public API wall; Metrics stay internal.
    """

    def project(self, instance: Instance) -> Mapping[str, Any] | Refuse:
        ...


class Compose(Protocol):
    """Multi-product answer — graph of Ensure / Join / Diff / Rank / Project.

    Composition may stay ephemeral (no persist of the composed node).
    """

    def compose(self, plan: Mapping[str, Any]) -> Instance | Mapping[str, Any] | Refuse:
        ...


class Invalidate(Protocol):
    """Lineage mark: needs_redo / cascade. No force-redo knob."""

    def invalidate(
        self,
        identity: Identity,
        *,
        cascade: bool = True,
    ) -> None:
        ...


class Gate(Protocol):
    """Policy stop — maturity, freshness, authority → Refuse or pass-through."""

    def gate(self, instance: Instance, ask: Ask) -> Instance | Refuse:
        ...


class Retire(Protocol):
    """Lifecycle: mint-new Instance, flip prior to retired. No mutate-in-place."""

    def retire(self, prior: Instance, successor: Instance) -> Instance:
        ...


class Explain(Protocol):
    """Structured provenance trail (term / lineage), not a Cypher walk."""

    def explain(self, instance: Instance) -> Mapping[str, Any]:
        ...
