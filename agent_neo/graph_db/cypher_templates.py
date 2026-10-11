"""Packaged Cypher templates for period rollup and populate invalidation."""


from __future__ import annotations

from pathlib import Path
from typing import Final, LiteralString

from django_neomodel.graph_db._core import load_query
from django_neomodel.graph_db.cypher_templates import load_query_text


__all__: tuple[LiteralString, ...] = (
    'COUNT_ROLLUPS_IN_WINDOW',
    'DELETE_ROLLUPS_IN_WINDOW',
    'FETCH_CACHE_KEYS_BY_SPINE_WINDOW',
    'FETCH_ROWS_BY_CACHE_KEYS',
    'MERGE_ROWS_BY_CACHE_KEY',
    'MERGE_ROWS_BY_CACHE_KEY_ON_MATCH',
    'PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW',
    'SCOPE_NAME_DB_PROPERTY',
)


#: On-disk Neo4j property that stores a computed node's ``scope_name``.
#:
#: The Python attribute is ``scope_name`` everywhere; only the stored property name
#: differs. It predates the attribute's rename and is kept so graphs written before
#: the rename stay readable without a data migration. Changing it means rewriting
#: that property on every node of every deployed graph (and its index), so treat it
#: as a schema constant. The packaged templates below hard-code the same name —
#: ``tests/agent_neo/test_scope_property.py`` pins the two together.
SCOPE_NAME_DB_PROPERTY: Final[str] = 'facility_name'


_MODULE_DIR = Path(__file__).parent
_CYPHER = _MODULE_DIR / 'cypher'
_PERIOD = _CYPHER / 'period_rollups'
_POPULATE = _CYPHER / 'populate'


FETCH_CACHE_KEYS_BY_SPINE_WINDOW = load_query(_PERIOD / 'fetch-cache-keys-by-spine-window.cypher')
MERGE_ROWS_BY_CACHE_KEY = load_query_text(_PERIOD / 'merge-rows-by-cache-key.cypher')
MERGE_ROWS_BY_CACHE_KEY_ON_MATCH = load_query_text(_PERIOD / 'merge-rows-by-cache-key-on-match.cypher')
FETCH_ROWS_BY_CACHE_KEYS = load_query(_PERIOD / 'fetch-rows-by-cache-keys.cypher')
PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW = load_query(
    _PERIOD / 'preload-period-rollups-by-spine-window.cypher',
)

COUNT_ROLLUPS_IN_WINDOW = load_query(_POPULATE / 'count-rollups-in-window.cypher')
DELETE_ROLLUPS_IN_WINDOW = load_query_text(_POPULATE / 'delete-rollups-in-window.cypher')
