"""Interpreter contracts: what a storage-bound engine must provide around the algebra.

The carrier operations are functions in :mod:`.algebra`; the gates are functions in
:mod:`.gates`. What remains here are the operations that *need a store* and therefore stay
Protocols the interpreter fulfils. Each is kept because a law needs it:

- :class:`Ensure` — the materialize-by-ask path (:data:`~.laws.LAW_ENSURE_IDEMPOTENT`).
- :class:`Retire` — mint-new, flip-prior (:data:`~.laws.LAW_RETIRE_NOT_MUTATE`).
- :class:`Invalidate` — the only way an instance becomes ``needs_redo``
  (:data:`~.laws.LAW_REDO_DERIVED`).

Warming (populate) is ``ensure`` over a sequence of asks in an order the interpreter chooses;
composing several products is ``join``/``map`` in :mod:`.algebra`; the serving boundary is
:func:`~agent_neo.a3.product.servable`; provenance is :meth:`Carrier.sources` and
``Instance.lineage``. None of those needs a contract of its own.
"""


from __future__ import annotations

from typing import Protocol

from agent_neo.a3.product import Ask, Identity, Instance, Refuse

__all__ = (
    'Ensure',
    'Invalidate',
    'Retire',
)


class Ensure(Protocol):
    """Resolve the ask, probe each identity, apply :func:`~agent_neo.a3.gates.gate`, and
    serve, recompute-and-persist, or refuse accordingly. Idempotent for unchanged inputs."""

    def ensure(self, ask: Ask) -> tuple[Instance | Refuse, ...]: ...


class Retire(Protocol):
    """Persist ``successor`` as current and flip ``prior`` to retired. Never mutate ``prior``'s payload."""

    def retire(self, prior: Instance | None, successor: Instance) -> Instance: ...


class Invalidate(Protocol):
    """Mark an identity — and, if ``cascade``, everything downstream of it — ``needs_redo``."""

    def invalidate(self, identity: Identity, *, cascade: bool = True) -> None: ...
