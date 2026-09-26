from __future__ import annotations

import pytest

from agent_neo.a3 import Lattice, MappingLattice


def test_up_and_down_walk_multiple_levels(space, time) -> None:
    assert isinstance(space, Lattice)
    assert space.up('zone', 'z1', 'floor') == {'f1'} and space.up('zone', 'z1', 'building') == {'b1'}
    assert space.down('building', 'b1', 'zone') == {'z1', 'z2', 'z3'} and space.down('floor', 'f1', 'zone') == {'z1', 'z2'}
    assert time.down('monthly', 'm1', 'hourly') == {'h1', 'h2', 'h3', 'h4'}
    assert space.up('zone', 'z1', 'zone') == {'z1'} and space.down('zone', 'z1', 'zone') == {'z1'}


def test_orphans_and_unknown_levels_are_empty_not_errors(space) -> None:
    assert space.up('zone', 'z9', 'floor') == frozenset() == space.up('zone', 'z1', 'campus') == space.down('floor', 'f9', 'zone')


def test_multi_parent_is_reported_not_hidden(overlapping_space) -> None:
    assert overlapping_space.up('zone', 'z2', 'floor') == {'f1', 'f2'} and overlapping_space.down('floor', 'f2', 'zone') == {'z2', 'z3'}


def test_law_lattice_consistent(space, time, overlapping_space) -> None:
    for lattice, pairs in ((space, (('zone', 'floor'), ('zone', 'building'), ('floor', 'building'))),
                           (time, (('hourly', 'daily'), ('hourly', 'monthly'), ('daily', 'monthly'))),
                           (overlapping_space, (('zone', 'floor'),))):
        nodes = {node for edge in lattice.edges for node in edge}
        for child_level, parent_level in pairs:
            for level, key in nodes:
                if level != child_level:
                    continue
                for parent in lattice.up(level, key, parent_level):
                    assert key in lattice.down(parent_level, parent, child_level)
            for level, key in nodes:
                if level != parent_level:
                    continue
                for child in lattice.down(level, key, child_level):
                    assert key in lattice.up(child_level, child, parent_level)


def test_self_parent_is_rejected() -> None:
    with pytest.raises(ValueError):
        MappingLattice(((('a', 'x'), ('a', 'x')),))
