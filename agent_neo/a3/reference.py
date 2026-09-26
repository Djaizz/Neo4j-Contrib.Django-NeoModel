"""A reference interpreter over an in-memory store: the proof that the blocks suffice.

Nothing here knows a database. :class:`MemoryStore` keeps every instance ever written, so the
laws about what a store must *not* do are observable; :class:`ReferenceInterpreter` is
``ensure`` written from the blocks alone — resolve, gate, evaluate the concept's term with
leaves ensured recursively, bridge, retire. Every law that a storage-bound interpreter must
obey (:data:`~agent_neo.a3.laws.LAW_ENSURE_IDEMPOTENT`,
:data:`~agent_neo.a3.laws.LAW_RETIRE_NOT_MUTATE`, :data:`~agent_neo.a3.laws.LAW_REDO_DERIVED`,
:data:`~agent_neo.a3.laws.LAW_ENSURE_RECURSIVE`) is tested against this module, and a real
interpreter is conformant when the same tests pass against its store.
"""


from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Iterable, Mapping

from agent_neo.a3.bridge import instances_from_carrier
from agent_neo.a3.gates import Verdict, gate
from agent_neo.a3.product import (
    PLAIN_KEY_SCHEME,
    Ask,
    Concept,
    Identity,
    Instance,
    KeyScheme,
    LifecycleStatus,
    LineageRef,
    Refuse,
    RefuseReason,
)
from agent_neo.a3.term import Env, evaluate, leaf_ask, leaves

__all__ = (
    'MemoryStore',
    'ReferenceInterpreter',
)


class MemoryStore:
    """:class:`~agent_neo.a3.bridge.Store`, :class:`~agent_neo.a3.ops.Retire` and
    :class:`~agent_neo.a3.ops.Invalidate` over a dict of histories.

    ``fetch`` returns instances with their lineage refs and producing status *refreshed* from
    what the store holds now — the facts the lineage gate decides from. A ref to a key the
    store has never held is returned as written: nothing is known about it.
    """

    def __init__(self, instances: Iterable[Instance] = (), *, scheme: KeyScheme = PLAIN_KEY_SCHEME,
                 recipe_status: Mapping[str, LifecycleStatus] | None = None) -> None:
        self.scheme = scheme
        self.recipe_status = dict(recipe_status or {})  # Concept.revision → its current lifecycle
        self._history: dict[str, list[Instance]] = {}
        for instance in instances:
            self.retire(None, instance)

    # -- Store ------------------------------------------------------------------

    def key(self, identity: Identity) -> str:
        return identity.cache_key(self.scheme)

    def history(self, identity: Identity) -> tuple[Instance, ...]:
        """Every instance ever written at the identity, oldest first, retired ones included."""
        return tuple(self._history.get(self.key(identity), ()))

    def current(self, identity: Identity) -> Instance | None:
        live = [i for i in self.history(identity) if i.lifecycle is not LifecycleStatus.RETIRED]
        if len(live) > 1:
            raise RuntimeError(f'{len(live)} current instances at {self.key(identity)!r}; at most one is allowed')
        return live[0] if live else None

    def present(self, identities: Iterable[Identity]) -> frozenset[Identity]:
        return frozenset(i for i in identities if self.current(i) is not None)

    def fetch(self, identities: Iterable[Identity]) -> tuple[Instance, ...]:
        found = (self.current(i) for i in identities)
        return tuple(self._refreshed(i) for i in found if i is not None)

    def _refreshed(self, instance: Instance) -> Instance:
        producing = self.recipe_status.get(instance.computed_by, instance.producing) if instance.computed_by else instance.producing
        return replace(instance, producing=producing, lineage=tuple(self._fact(ref) for ref in instance.lineage))

    def _fact(self, ref: LineageRef) -> LineageRef:
        rows = self._history.get(ref.key)
        if not rows:
            return ref
        live = [r for r in rows if r.lifecycle is not LifecycleStatus.RETIRED]
        latest = live[-1] if live else rows[-1]
        return LineageRef(ref.key, latest.lifecycle, latest.needs_redo, latest.computed_at)

    # -- Retire -----------------------------------------------------------------

    def retire(self, prior: Instance | None, successor: Instance) -> Instance:
        """Append ``successor`` as current; flip the current instance to RETIRED. The retired
        row keeps its payload and stays in the history."""
        key = self.key(successor.identity)
        current = self.current(successor.identity)
        if prior is None and current is not None:
            raise ValueError(f'an instance is current at {key!r}; pass it as prior')
        if prior is not None and (current is None or self.key(prior.identity) != key):
            raise ValueError(f'prior is not the current instance at {key!r}')
        rows = self._history.setdefault(key, [])
        if current is not None:
            rows[rows.index(current)] = replace(current, lifecycle=LifecycleStatus.RETIRED)
        rows.append(successor)
        return successor

    # -- Invalidate -------------------------------------------------------------

    def invalidate(self, identity: Identity, *, cascade: bool = True) -> None:
        """Flag the current instance. With ``cascade``, flag everything whose lineage reaches
        it. The cascade is an optimisation, not a requirement: a dependent that was *not*
        flagged still recomputes, because its refreshed refs say its upstream is flagged."""
        key = self.key(identity)
        self._flag(key)
        if cascade:
            for dependent in self._dependents(key):
                self._flag(dependent)

    def _flag(self, key: str) -> None:
        rows = self._history.get(key, [])
        for index, row in enumerate(rows):
            if row.lifecycle is not LifecycleStatus.RETIRED and not row.needs_redo:
                rows[index] = replace(row, needs_redo=True)

    def _dependents(self, key: str) -> list[str]:
        seen: list[str] = []
        frontier = [key]
        while frontier:
            upstream = frontier.pop()
            for other, rows in self._history.items():
                if other in seen or other == key:
                    continue
                if any(r.lifecycle is not LifecycleStatus.RETIRED and any(ref.key == upstream for ref in r.lineage) for r in rows):
                    seen.append(other)
                    frontier.append(other)
        return seen


@dataclass
class ReferenceInterpreter:
    """:class:`~agent_neo.a3.ops.Ensure` from the blocks alone.

    ``env.store`` is a :class:`MemoryStore`; ``clock`` is the injected ``now``. The leaves of a
    concept's term are ensured *before* its own instances are gated, so asking for a view asks
    for everything under it, and a change anywhere below is seen through refreshed lineage refs
    at every level up. A concept with a term persists its result into its one declared field; a
    concept without a term is observed, not computed, and a missing or invalid instance of it is
    refused. A recompute the algebra refuses leaves the prior instance flagged, so what depends
    on it sees an invalid upstream rather than a quiet, stale one.
    """

    env: Env
    clock: Callable[[], datetime]

    @property
    def store(self) -> MemoryStore:
        return self.env.store  # type: ignore[return-value]

    def ensure(self, ask: Ask) -> tuple[Instance | Refuse, ...]:
        concept = self.env.concepts[ask.product]
        env = replace(self.env, ask=ask)
        served: dict[Ask, tuple[Instance | Refuse, ...]] = {}
        if concept.term is not None:
            for leaf in leaves(concept.term):  # type: ignore[arg-type]
                upstream = leaf_ask(leaf, env)
                served.setdefault(upstream, self.ensure(upstream))  # upstream first: its refs are then facts
        env = replace(env, ensure=served.__getitem__)  # the term reads exactly what was served
        identities = tuple(Identity(i.product, env.scheme.canonical(i.coordinate)) for i in env.resolver.resolve(ask))
        now = self.clock()
        found = {instance.identity: instance for instance in self.store.fetch(identities)}
        outcomes = {i: gate(found.get(i), ask, now=now, exclusive_end=self._exclusive_end(i)) for i in identities}
        stale = tuple(i for i in identities if outcomes[i].verdict is Verdict.RECOMPUTE)
        refused: dict[Identity, Refuse] = {i: outcomes[i].refusal for i in identities if outcomes[i].verdict is Verdict.REFUSE}  # type: ignore[misc]
        if stale:
            for identity, result in self._compute(concept, env, stale, found, now).items():
                if isinstance(result, Refuse):
                    refused[identity] = result
                    if identity in found and not found[identity].needs_redo:
                        self.store.invalidate(identity, cascade=False)
            found = {instance.identity: instance for instance in self.store.fetch(identities)}  # as the store now serves them
        return tuple(refused[i] if i in refused else found[i] for i in identities)

    def _exclusive_end(self, identity: Identity) -> datetime | None:
        return self.env.exclusive_end(*identity.coordinate.period) if self.env.exclusive_end is not None else None

    def _compute(self, concept: Concept, env: Env, stale: tuple[Identity, ...], found: Mapping[Identity, Instance],
                 now: datetime) -> dict[Identity, Instance | Refuse]:
        ask: Ask = env.ask  # type: ignore[assignment]
        if concept.term is None:
            return {i: Refuse(RefuseReason.NO_RECIPE, f'{concept.family!r} is observed, not computed; nothing current at {self.store.key(i)!r}',
                              {'identity': i}) for i in stale}
        if len(concept.fields) != 1:
            raise ValueError(f'{concept.family!r} declares {len(concept.fields)} fields; a term computes exactly one')
        (field_name, spec), = concept.fields
        result = evaluate(concept.term, replace(env, now=now))  # type: ignore[arg-type]
        if isinstance(result, Refuse):
            return dict.fromkeys(stale, result)
        written = instances_from_carrier(result, product=ask.product, computed_at=now, computed_by=concept.revision, field=field_name,
                                         spec=spec, operators=env.operators, scheme=env.scheme, producing=concept.lifecycle)
        if isinstance(written, Refuse):
            return dict.fromkeys(stale, written)
        minted = {instance.identity: instance for instance in written}
        out: dict[Identity, Instance | Refuse] = {}
        for identity in stale:
            if identity.coordinate not in result.expected:
                out[identity] = Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'the recipe of {concept.family!r} does not produce {self.store.key(identity)!r}',
                                       {'identity': identity})
            elif identity in minted:
                out[identity] = self.store.retire(found.get(identity), minted[identity])
            else:
                out[identity] = Refuse(RefuseReason.INCOMPLETE_PARTITION, f'nothing to persist at {self.store.key(identity)!r}',
                                       {'identity': identity, 'gap': result.gaps.get(identity.coordinate, frozenset())})
        return out
