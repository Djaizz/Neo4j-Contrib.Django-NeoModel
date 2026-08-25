"""Tests for the pre-check that skips ``install_all_labels`` on a complete schema.

The install issues one statement per indexed property per model class — hundreds on
a real schema, every one of them a no-op on a database that already has them. The
pre-check replaces that with one ``SHOW INDEXES`` and one ``SHOW CONSTRAINTS``.

Every test here exists to protect the same asymmetry: skipping when the schema is
in fact incomplete leaves a query running unindexed forever, while installing when
it was already complete merely costs seconds. So the gate is ``expected ⊆ observed``
and nothing else, and every doubt resolves to "install".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import agent_neo.graph_db._core as graph_core


# ============================================================================
# Fakes: a model tree shaped like the ones the fork's install walks
# ============================================================================

class _FakeProperty:
    def __init__(
        self,
        *,
        index: bool = False,
        unique_index: bool = False,
        fulltext_index: object | None = None,
        vector_index: object | None = None,
        db_name: str | None = None,
    ) -> None:
        self.index = index
        self.unique_index = unique_index
        self.fulltext_index = fulltext_index
        self.vector_index = vector_index
        self._db_name = db_name

    def get_db_property_name(self, name: str) -> str:
        return self._db_name or name


class _FakeRelationshipDefinition:
    def __init__(self, *, model: Any, relation_type: str) -> None:
        self.definition = {'model': model, 'relation_type': relation_type}


def _fake_model(
    label: str | None,
    properties: dict[str, _FakeProperty],
    relationships: dict[str, _FakeRelationshipDefinition] | None = None,
) -> type:
    namespace: dict[str, Any] = {
        '_fake_properties': properties,
        '_fake_relationships': relationships or {},
    }
    if label is not None:
        namespace['__label__'] = label

    def defined_properties(
        cls: type,
        aliases: bool = True,
        properties: bool = True,
        rels: bool = True,
    ) -> dict[str, Any]:
        if rels and not properties:
            return cls._fake_relationships  # type: ignore[attr-defined]
        return cls._fake_properties  # type: ignore[attr-defined]

    namespace['defined_properties'] = classmethod(defined_properties)
    return type(f'Fake{label or "Abstract"}', (), namespace)


_REL_MODEL = _fake_model(
    None,
    {
        'since': _FakeProperty(index=True),
        'ticket': _FakeProperty(unique_index=True),
    },
)

_WIDGET = _fake_model(
    'Widget',
    {
        'uuid': _FakeProperty(unique_index=True),
        'name': _FakeProperty(index=True),
        'blurb': _FakeProperty(fulltext_index=object()),
        'embedding': _FakeProperty(vector_index=object()),
        'renamed': _FakeProperty(index=True, db_name='renamed_in_db'),
        'plain': _FakeProperty(),
    },
    {'gadgets': _FakeRelationshipDefinition(model=_REL_MODEL, relation_type='HAS_GADGET')},
)

_ABSTRACT = _fake_model(None, {'uuid': _FakeProperty(unique_index=True)})

_UNMODELLED_REL = _fake_model(
    'Gadget',
    {'uuid': _FakeProperty(unique_index=True)},
    {'loose': _FakeRelationshipDefinition(model=None, relation_type='LOOSE')},
)

_EXPECTED_INDEXES = frozenset({
    'index_Widget_name',
    'fulltext_index_Widget_blurb',
    'vector_index_Widget_embedding',
    'index_Widget_renamed_in_db',
    'index_HAS_GADGET_since',
})
_EXPECTED_CONSTRAINTS = frozenset({
    'constraint_unique_Widget_uuid',
    'constraint_unique_HAS_GADGET_ticket',
    'constraint_unique_Gadget_uuid',
})


class _FakeDb:
    """Just enough of the neomodel singleton for the pre-check to talk to."""

    def __init__(
        self,
        *,
        index_names: set[str] | None = None,
        constraint_names: set[str] | None = None,
        show_raises: bool = False,
    ) -> None:
        self._index_names = index_names if index_names is not None else set()
        self._constraint_names = (
            constraint_names if constraint_names is not None else set()
        )
        self._show_raises = show_raises
        self.install_call_count = 0

    def list_indexes(self, exclude_token_lookup: bool = False) -> list[dict[str, Any]]:
        if self._show_raises:
            raise RuntimeError('SHOW INDEXES is not available on this server')
        return [{'name': name, 'type': 'RANGE'} for name in sorted(self._index_names)]

    def list_constraints(self) -> list[dict[str, Any]]:
        if self._show_raises:
            raise RuntimeError('SHOW CONSTRAINTS is not available on this server')
        return [{'name': name} for name in sorted(self._constraint_names)]

    def install_all_labels(self, stdout: Any = None) -> None:
        self.install_call_count += 1


def _with_fake_models(*model_classes: type) -> Any:
    return patch.object(
        graph_core, '_structured_node_subclasses', lambda _cls: list(model_classes),
    )


# ============================================================================
# Deriving the expected names
# ============================================================================

def test_expected_names_match_the_forks_own_name_formats() -> None:
    """Six emitters, six formats. A drift here is a wrong answer, not a slow one."""
    with _with_fake_models(_WIDGET, _ABSTRACT, _UNMODELLED_REL):
        expected = graph_core._expected_schema_object_names()
    assert expected == (_EXPECTED_INDEXES, _EXPECTED_CONSTRAINTS)


def test_index_wins_over_unique_index_on_the_same_property() -> None:
    """The install's two branches are ``elif``-exclusive; so are ours."""
    both = _fake_model('Both', {'key': _FakeProperty(index=True, unique_index=True)})
    with _with_fake_models(both):
        index_names, constraint_names = graph_core._expected_schema_object_names()
    assert index_names == {'index_Both_key'}
    assert constraint_names == frozenset()


def test_an_abstract_class_contributes_nothing() -> None:
    """``install_labels`` returns early without ``__label__``; so must we, or we
    would expect an index the install never creates and then never skip."""
    with _with_fake_models(_ABSTRACT):
        assert graph_core._expected_schema_object_names() == (
            frozenset(), frozenset(),
        )


def test_derivation_failure_returns_none_rather_than_an_empty_set() -> None:
    """``None`` and "nothing expected" must not be the same value.

    An empty expected set is a subset of every observed set, so returning it for
    an underivable schema would turn a failure into an unconditional skip.
    """
    def _explode(_cls: Any) -> list[type]:
        raise TypeError('model tree is not walkable')

    with patch.object(graph_core, '_structured_node_subclasses', _explode):
        assert graph_core._expected_schema_object_names() is None


# ============================================================================
# The gate
# ============================================================================

def test_skips_when_every_expected_object_is_present() -> None:
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        constraint_names=set(_EXPECTED_CONSTRAINTS),
    )
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is True


def test_extra_objects_in_the_database_still_skip() -> None:
    """A superset is complete. Indexes this schema did not ask for are not its
    business, and the install would not have removed them either."""
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES) | {'index_Something_else', 'token_lookup'},
        constraint_names=set(_EXPECTED_CONSTRAINTS) | {'constraint_unique_Other_uuid'},
    )
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is True


def test_one_missing_index_falls_through_to_the_full_install() -> None:
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES) - {'index_Widget_name'},
        constraint_names=set(_EXPECTED_CONSTRAINTS),
    )
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is False


def test_one_missing_constraint_falls_through_to_the_full_install() -> None:
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        constraint_names=set(_EXPECTED_CONSTRAINTS) - {'constraint_unique_Widget_uuid'},
    )
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is False


def test_a_constraint_present_only_as_an_index_does_not_count() -> None:
    """Neo4j names a constraint's backing index after the constraint, so a union
    check would read the backing index as the constraint. Uniqueness is not
    something an index alone provides."""
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES) | {'constraint_unique_Widget_uuid'},
        constraint_names=set(_EXPECTED_CONSTRAINTS) - {'constraint_unique_Widget_uuid'},
    )
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is False


def test_a_fresh_empty_database_installs() -> None:
    fake_db = _FakeDb(index_names=set(), constraint_names=set())
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is False


def test_a_failing_show_statement_installs() -> None:
    fake_db = _FakeDb(show_raises=True)
    with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
        graph_core, 'db', fake_db,
    ):
        assert graph_core._schema_is_already_complete() is False


def test_an_underivable_expected_set_installs_without_querying_the_database() -> None:
    fake_db = _FakeDb(show_raises=True)
    with patch.object(
        graph_core, '_expected_schema_object_names', lambda: None,
    ), patch.object(graph_core, 'db', fake_db):
        assert graph_core._schema_is_already_complete() is False


def test_nothing_expected_installs_rather_than_skipping_on_a_vacuous_subset() -> None:
    """No models registered means no expectations, and ``set() <= anything`` is
    ``True``. Treating that as "complete" is how a populate silently ships with no
    indexes at all."""
    fake_db = _FakeDb(index_names={'index_Widget_name'})
    with _with_fake_models(_ABSTRACT), patch.object(graph_core, 'db', fake_db):
        assert graph_core._schema_is_already_complete() is False


# ============================================================================
# Wiring: _install_labels and the ordering the gate depends on
# ============================================================================

def _restore_callback(previous: Any) -> None:
    graph_core.set_label_install_callback(previous)


def test_install_labels_skips_the_install_when_the_schema_is_complete() -> None:
    previous = graph_core._label_install_callback
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        constraint_names=set(_EXPECTED_CONSTRAINTS),
    )
    try:
        graph_core.set_label_install_callback(lambda: fake_db.install_all_labels())
        with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
            graph_core, 'db', fake_db,
        ):
            graph_core._install_labels()
    finally:
        _restore_callback(previous)
    assert fake_db.install_call_count == 0


def test_install_labels_runs_the_install_when_the_schema_is_incomplete() -> None:
    previous = graph_core._label_install_callback
    fake_db = _FakeDb(index_names=set(), constraint_names=set())
    try:
        graph_core.set_label_install_callback(lambda: fake_db.install_all_labels())
        with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
            graph_core, 'db', fake_db,
        ):
            graph_core._install_labels()
    finally:
        _restore_callback(previous)
    assert fake_db.install_call_count == 1


def test_the_gate_reads_the_model_tree_after_the_callback_registered_it() -> None:
    """The ordering the whole design turns on.

    A registration callback's side-effect imports are what put the model classes
    in the tree. Deriving the expectations *before* it runs gates on whatever
    subset happened to be imported already — and a subset of the expectations is a
    subset of the observations, so the gate would skip and the unregistered
    model's index would never be created. Here ``Gadget`` arrives only when the
    callback runs, and its constraint is absent from the database: the gate must
    see it and install.
    """
    previous = graph_core._label_install_callback
    registered: list[type] = [_WIDGET]
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        # Widget's and the relationship's constraints exist; Gadget's does not.
        constraint_names=set(_EXPECTED_CONSTRAINTS) - {'constraint_unique_Gadget_uuid'},
    )

    def _callback() -> None:
        registered.append(_UNMODELLED_REL)  # the "side-effect import"
        fake_db.install_all_labels()

    try:
        graph_core.set_label_install_callback(_callback)
        with patch.object(
            graph_core, '_structured_node_subclasses', lambda _cls: list(registered),
        ), patch.object(graph_core, 'db', fake_db):
            graph_core._install_labels()
    finally:
        _restore_callback(previous)
    assert fake_db.install_call_count == 1, (
        'the gate must derive its expectations after the callback registered its '
        'models, or a late-registered index is silently skipped'
    )


def test_the_wrapper_restores_install_all_labels_even_when_the_callback_raises() -> None:
    previous = graph_core._label_install_callback
    fake_db = _FakeDb()
    original = fake_db.install_all_labels

    def _callback() -> None:
        raise RuntimeError('models failed to import')

    try:
        graph_core.set_label_install_callback(_callback)
        with patch.object(graph_core, 'db', fake_db):
            try:
                graph_core._install_labels()
            except RuntimeError:
                pass
    finally:
        _restore_callback(previous)
    assert 'install_all_labels' not in vars(fake_db)
    assert fake_db.install_all_labels == original


def test_the_precheck_can_be_switched_off_by_environment() -> None:
    previous = graph_core._label_install_callback
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        constraint_names=set(_EXPECTED_CONSTRAINTS),
    )
    try:
        graph_core.set_label_install_callback(lambda: fake_db.install_all_labels())
        with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
            graph_core, 'db', fake_db,
        ), patch.dict('os.environ', {'AGENT_NEO_LABEL_INSTALL_PRECHECK': '0'}):
            graph_core._install_labels()
    finally:
        _restore_callback(previous)
    assert fake_db.install_call_count == 1


def test_a_callback_that_installs_some_other_way_is_simply_not_gated() -> None:
    """No silent behaviour change for a consumer that does not call
    ``install_all_labels``."""
    previous = graph_core._label_install_callback
    fake_db = _FakeDb(
        index_names=set(_EXPECTED_INDEXES),
        constraint_names=set(_EXPECTED_CONSTRAINTS),
    )
    per_class_installs: list[str] = []
    try:
        graph_core.set_label_install_callback(
            lambda: per_class_installs.append('Widget'),
        )
        with _with_fake_models(_WIDGET, _UNMODELLED_REL), patch.object(
            graph_core, 'db', fake_db,
        ):
            graph_core._install_labels()
    finally:
        _restore_callback(previous)
    assert per_class_installs == ['Widget']
    assert fake_db.install_call_count == 0
