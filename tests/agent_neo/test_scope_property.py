"""The scope property: one stored name, used by every write path and packaged query."""


from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from neomodel.properties import StringProperty

from agent_neo.analytical_product.abstract import (
    AbstractAnalyticalComputedProduct,
    ComputedNodeResult,
)
from agent_neo.analytical_product.computed_product_bulk_persist import _upsert_row
from agent_neo.analytical_product.identity import AnalyticalProductIdentity
from agent_neo.analytical_product.period_spine import PeriodSpineMixin
from agent_neo.graph_db import cypher_templates
from agent_neo.graph_db.cypher_templates import SCOPE_NAME_DB_PROPERTY


class ScopeInheritingMetricSet(AbstractAnalyticalComputedProduct):
    """Declares nothing about scope — relies on the inherited ``scope_name``, as documented."""


class StoredNameRedeclaringMetricSet(AbstractAnalyticalComputedProduct):
    """Also declares a Python attribute named after the stored property, as older subclasses do."""

    facility_name = StringProperty(required=True, index=True)


def _stored_properties(product_class: type) -> dict[str, object]:
    identity = AnalyticalProductIdentity(
        analytical_product_class_name=product_class.__name__,
        scope_name='example-scope',
        subject_kind='item',
        subject_key='item-1',
        temporal_granularity='daily',
        local_period_start=datetime(2026, 5, 1, tzinfo=UTC),
        local_period_end=datetime(2026, 5, 2, tzinfo=UTC),
    )
    row = _upsert_row(
        product_class,
        identity,
        ComputedNodeResult(payload={}, computes_concept=SimpleNamespace(product_kind='METRIC')),
        local_tz=UTC,
        now=datetime(2026, 5, 3, tzinfo=UTC),
        now_epoch_seconds=1.0,
    )
    return row['properties']


def test_scope_is_stored_for_a_product_that_only_inherits_it() -> None:
    # Regression: the write path once keyed the scope by its *stored* name, which the
    # model's attribute map does not contain, so the scope was silently dropped.
    assert _stored_properties(ScopeInheritingMetricSet)[SCOPE_NAME_DB_PROPERTY] == 'example-scope'


def test_scope_is_stored_identically_when_a_subclass_redeclares_the_stored_name() -> None:
    assert _stored_properties(StoredNameRedeclaringMetricSet)[SCOPE_NAME_DB_PROPERTY] == 'example-scope'


def test_node_declarations_store_scope_under_the_constant() -> None:
    declared = AbstractAnalyticalComputedProduct.defined_properties(aliases=False, rels=False)['scope_name']
    assert declared.get_db_property_name('scope_name') == SCOPE_NAME_DB_PROPERTY
    assert PeriodSpineMixin.scope_name.get_db_property_name('scope_name') == SCOPE_NAME_DB_PROPERTY


@pytest.mark.parametrize(
    'template_name',
    [
        'COUNT_ROLLUPS_IN_WINDOW',
        'DELETE_ROLLUPS_IN_WINDOW',
        'FETCH_CACHE_KEYS_BY_SPINE_WINDOW',
        'PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW',
    ],
)
def test_packaged_templates_filter_on_the_stored_scope_property(template_name: str) -> None:
    template = getattr(cypher_templates, template_name)
    text = getattr(template, 'query', template)
    assert f'n.{SCOPE_NAME_DB_PROPERTY} = $scope_name' in text
