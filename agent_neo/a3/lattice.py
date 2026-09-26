"""The lattice: the structure ``roll`` consults, and the only thing that knows a hierarchy.

A carrier's coordinates are flat strings; nothing in them says that zone ``z1`` is on
floor ``f1`` or that hour ``2026-05-01T09:00`` is inside day ``2026-05-01``. That knowledge
is a *slot* the domain fills. Both rollable dimensions have the same shape — a ``(level,
key)`` pair where the level is already a coordinate field — so one protocol serves both.

``up`` returns a *set* of parents on purpose. A partition has exactly one; zero means the
key is an orphan at that level; more than one means the hierarchy double-counts, and the
algebra must refuse to roll through it rather than sum the child twice. The lattice
reports the topology truthfully; judging it is the algebra's job.

``down`` is the coverage denominator: the children a parent *should* have, which is how
a roll can see a child that was never present at all.
"""


from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = (
    'Lattice',
    'MappingLattice',
    'Node',
)


Node = tuple[str, str]  # (level, key)


@runtime_checkable
class Lattice(Protocol):
    def up(self, level: str, key: str, to_level: str) -> frozenset[str]:
        """Keys at ``to_level`` that ``(level, key)`` rolls into. One for a partition."""
        ...

    def down(self, level: str, key: str, to_level: str) -> frozenset[str]:
        """Keys at ``to_level`` that roll into ``(level, key)`` — the expected children."""
        ...


@dataclass(frozen=True)
class MappingLattice:
    """A lattice given explicitly as child → parent edges between ``(level, key)`` nodes.

    Multi-step traversal is supported: ``up('zone', 'z1', 'site')`` walks zone → floor →
    building → site if those edges exist. A child may be given more than one parent at the
    same level; ``up`` will then report both, and a roll through it will be refused as
    double-counted — which is the point of allowing it.
    """

    edges: tuple[tuple[Node, Node], ...] = ()
    _parents: dict[Node, frozenset[Node]] = field(init=False, repr=False, compare=False)
    _children: dict[Node, frozenset[Node]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        parents: defaultdict[Node, set[Node]] = defaultdict(set)
        children: defaultdict[Node, set[Node]] = defaultdict(set)
        for child, parent in self.edges:
            if child == parent:
                raise ValueError(f'a node cannot be its own parent: {child!r}')
            parents[child].add(parent)
            children[parent].add(child)
        object.__setattr__(self, '_parents', {node: frozenset(ps) for node, ps in parents.items()})
        object.__setattr__(self, '_children', {node: frozenset(cs) for node, cs in children.items()})

    @classmethod
    def from_parent_map(cls, level: str, to_level: str, parent_of: dict[str, str]) -> MappingLattice:
        """Convenience for the single-step, single-parent case."""
        return cls(tuple(((level, child), (to_level, parent)) for child, parent in parent_of.items()))

    def _reach(self, start: Node, to_level: str, step: dict[Node, frozenset[Node]]) -> frozenset[str]:
        frontier, seen, found = {start}, {start}, set()
        while frontier:
            nxt: set[Node] = set()
            for node in frontier:
                for neighbour in step.get(node, ()):
                    if neighbour[0] == to_level:
                        found.add(neighbour[1])
                    elif neighbour not in seen:
                        nxt.add(neighbour)
                    seen.add(neighbour)
            frontier = nxt
        return frozenset(found)

    def up(self, level: str, key: str, to_level: str) -> frozenset[str]:
        if level == to_level:
            return frozenset({key})
        return self._reach((level, key), to_level, self._parents)

    def down(self, level: str, key: str, to_level: str) -> frozenset[str]:
        if level == to_level:
            return frozenset({key})
        return self._reach((level, key), to_level, self._children)

    def __or__(self, other: MappingLattice) -> MappingLattice:
        """Two lattices over different dimensions (or levels) combine by union of edges."""
        return MappingLattice(self.edges + other.edges)
