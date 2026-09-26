"""Product vocabulary: shared enums, hashable coordinates, concepts, and key parity with the interpreter."""


from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_neo.a3 import (
    Ask,
    Concept,
    Coordinate,
    Dimension,
    Field,
    FieldRole,
    Identity,
    KeyScheme,
    Layer,
    LifecycleStatus,
    freeze_classifications,
)


def test_interpreter_enums_are_the_algebra_enums_not_copies() -> None:
    from agent_neo.analytical_product.enum import ComputedNodeLayer, NodeLifecycleStatus

    assert ComputedNodeLayer is Layer and NodeLifecycleStatus is LifecycleStatus
    assert ComputedNodeLayer.METRIC is Layer.METRIC
    assert {s.value: s.value for s in NodeLifecycleStatus} == {'official': 'official', 'provisional': 'provisional', 'retired': 'retired'}


def test_enum_names_and_values_are_persisted_data_and_must_not_drift() -> None:
    # Layer member NAMES are stored as product_kind on every node; LifecycleStatus VALUES as lifecycle_status.
    assert [m.name for m in Layer] == ['SOURCE', 'FACT', 'METRIC', 'INTERPRETATION', 'VIEW'] and [m.value for m in Layer] == [0, 1, 2, 3, 4]
    assert [s.value for s in LifecycleStatus] == ['official', 'provisional', 'retired']


def test_layer_rules() -> None:
    assert Layer.VIEW.may_depend_on(Layer.METRIC) and not Layer.METRIC.may_depend_on(Layer.VIEW) and Layer.METRIC.may_depend_on(Layer.METRIC)
    assert [layer.is_served for layer in Layer] == [False, False, False, False, True]
    assert Layer.SOURCE.rank == 0 and Layer.VIEW.label == 'view'


def _coord(**classifications: str) -> Coordinate:
    return Coordinate('scope', 'zone', 'z1', 'daily', '2026-05-01', classifications)


def test_coordinate_is_hashable_and_classification_order_does_not_matter() -> None:
    a = _coord(day='weekday', hour='all')
    b = Coordinate('scope', 'zone', 'z1', 'daily', '2026-05-01', {'hour': 'all', 'day': 'weekday'})
    assert hash(a) == hash(b) and a == b and {a: 1}[b] == 1
    assert a.classifications == (('day', 'weekday'), ('hour', 'all'))


def test_coordinate_dimensions_and_moves() -> None:
    c = _coord()
    assert c.along(Dimension.SUBJECT) == ('zone', 'z1') and c.along(Dimension.PERIOD) == ('daily', '2026-05-01')
    up = c.moved(Dimension.SUBJECT, 'floor', 'f1')
    assert up.subject == ('floor', 'f1') and up.period == c.period and up.scope_name == c.scope_name
    assert c.with_classifications(day='weekend').classification('day') == 'weekend' and c.classification('missing') is None


def test_duplicate_classification_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        freeze_classifications([('day', 'a'), ('day', 'b')])


# ---------------------------------------------------------------------------
# Concepts and fields
# ---------------------------------------------------------------------------


def test_field_roles_must_be_consistent_with_an_operator() -> None:
    Field(FieldRole.LEAF)
    Field(FieldRole.ACCUMULATOR, 'mean')
    with pytest.raises(ValueError):
        Field(FieldRole.LEAF, 'mean')
    with pytest.raises(ValueError):
        Field(FieldRole.REPORTED)


def test_concept_key_family_and_fields() -> None:
    c = Concept('usage', 'r2', Layer.METRIC, fields={'usage': Field(FieldRole.LEAF), 'usage_acc': Field(FieldRole.ACCUMULATOR, 'sum')})
    assert c.key == 'usage@r2' and c.depends_on == frozenset() and c.field('usage_acc').operator == 'sum'
    with pytest.raises(KeyError):
        c.field('nope')


def test_ask_may_name_every_subject_of_a_kind() -> None:
    every = Ask('usage', 'site', 'floor', None, 'daily')
    one = Ask('usage', 'site', 'floor', 'f1', 'daily', classifications={'shift': 'day'})
    assert every.subject_key is None and one.classifications == (('shift', 'day'),)


# ---------------------------------------------------------------------------
# Key parity: an a3 identity under the interpreter's scheme writes the interpreter's key
# ---------------------------------------------------------------------------

INTERPRETER_SCHEME = KeyScheme(entries=(('day_classif', 'd', 'all'), ('hour_classif', 'h', 'all')))


@pytest.mark.parametrize(('day', 'hour'), [('all', 'all'), ('weekday', 'all'), ('all', 'operating'), ('weekend', 'operating')])
@pytest.mark.parametrize('granularity', ['hourly', 'daily', 'weekly', 'monthly'])
@pytest.mark.parametrize('carry', ['both', 'only-non-neutral'], ids=['coordinate carries both', 'coordinate carries only the sliced one'])
def test_identity_cache_key_matches_the_interpreters_build_cache_key(granularity: str, day: str, hour: str, carry: str) -> None:
    from agent_neo.analytical_product.identity import build_cache_key
    from agent_neo.util.datetime import period_anchor

    start = datetime(2026, 5, 6, 9, tzinfo=UTC)
    expected = build_cache_key(
        analytical_product_class_name='ExampleMetricSet', scope_name='scope', subject_kind='zone', subject_key='z1',
        temporal_granularity=granularity, local_period_start=start, day_classif=day, hour_classif=hour,
    )
    classifications = {'day_classif': day, 'hour_classif': hour}
    if carry == 'only-non-neutral':
        classifications = {k: v for k, v in classifications.items() if v != 'all'}  # the coordinate omits neutral ones; the scheme fills them in
    coordinate = Coordinate('scope', 'zone', 'z1', granularity, period_anchor(temporal_granularity=granularity, local_period_start=start), classifications)
    assert Identity('ExampleMetricSet', coordinate).cache_key(INTERPRETER_SCHEME) == expected


def test_canonical_drops_explicit_neutral_pairs_so_one_slot_has_one_coordinate() -> None:
    explicit, implicit = _coord(day_classif='all', hour_classif='operating'), _coord(hour_classif='operating')
    assert explicit != implicit and Identity('P', explicit).cache_key(INTERPRETER_SCHEME) == Identity('P', implicit).cache_key(INTERPRETER_SCHEME)
    assert INTERPRETER_SCHEME.canonical(explicit) == implicit and INTERPRETER_SCHEME.canonical(implicit) is implicit
    assert INTERPRETER_SCHEME.canonical(_coord(day_classif='all', hour_classif='all')) == _coord()


def test_unknown_classifications_follow_the_scheme_in_name_order() -> None:
    identity = Identity('P', _coord(day_classif='weekday', shift='day'))
    assert identity.cache_key(INTERPRETER_SCHEME) == 'P|scope|zone=z1|daily|2026-05-01|d=weekday|h=all|shift=day'
    assert identity.cache_key() == 'P|scope|zone=z1|daily|2026-05-01|day_classif=weekday|shift=day'
    assert Identity('P', _coord()).cache_key() == Identity('P', _coord()).cache_key(INTERPRETER_SCHEME) == 'P|scope|zone=z1|daily|2026-05-01'
