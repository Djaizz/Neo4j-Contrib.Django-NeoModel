"""Lineage explainability: walk dependency edges from a cache key."""


from __future__ import annotations

from typing import Any, LiteralString, Sequence

from neomodel.sync_.database import db

from agent_neo.util.json_safe import json_safe_structure


__all__: tuple[LiteralString, ...] = (
    'build_explain_envelope',
    'explain_lineage_for_rows',
    'explain_lineage_from_cache_key',
)


def explain_lineage_for_rows(
    rows: list[dict[str, Any]],
    *,
    lineage_relationship_types: Sequence[str],
    max_depth: int = 10,
) -> dict[str, Any] | None:
    """Explain the first row that carries a ``cache_key``, if any."""
    for row in rows:
        cache_key = str(row.get('cache_key') or '').strip()
        if cache_key:
            return explain_lineage_from_cache_key(
                cache_key,
                lineage_relationship_types=lineage_relationship_types,
                max_depth=max_depth,
            )
    return None


def build_explain_envelope(
    rows: list[dict[str, Any]],
    *,
    explain: bool,
    lineage_relationship_types: Sequence[str],
    max_depth: int = 10,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return plain rows or an envelope with lineage when ``explain`` is requested."""
    if not explain:
        return rows
    envelope: dict[str, Any] = {'rows': rows}
    lineage = explain_lineage_for_rows(
        rows,
        lineage_relationship_types=lineage_relationship_types,
        max_depth=max_depth,
    )
    if lineage is not None:
        envelope['explain'] = lineage
    return envelope


def explain_lineage_from_cache_key(
    cache_key: str,
    *,
    lineage_relationship_types: Sequence[str],
    max_depth: int = 10,
) -> dict[str, Any]:
    """Return a downward lineage tree from *cache_key* through *lineage_relationship_types*."""
    clean_cache_key = str(cache_key or '').strip()
    if not clean_cache_key:
        raise ValueError('cache_key must not be empty')
    clean_relationship_types = tuple(
        relationship_type.strip()
        for relationship_type in lineage_relationship_types
        if str(relationship_type or '').strip()
    )
    if not clean_relationship_types:
        raise ValueError('lineage_relationship_types must not be empty')

    root_query = """
    MATCH (root {cache_key: $cache_key})
    RETURN root.cache_key AS cache_key,
           labels(root) AS labels,
           root.lifecycle_status AS lifecycle_status,
           root.time_granularity AS time_granularity,
           root.subject_kind AS subject_kind,
           root.subject_key AS subject_key
    LIMIT 1
    """
    root_rows, _ = db.cypher_query(root_query, {'cache_key': clean_cache_key})
    if not root_rows:
        raise ValueError(f'No analytical product found for cache_key={clean_cache_key!r}')

    relationship_pattern = '|'.join(clean_relationship_types)
    max_depth_int = max(1, min(int(max_depth), 20))
    lineage_query = f"""
    MATCH (root {{cache_key: $cache_key}})
    OPTIONAL MATCH path = (root)-[:{relationship_pattern}*1..{max_depth_int}]->(dependent)
    WITH root, collect(DISTINCT dependent) AS dependents
    UNWIND (CASE WHEN size(dependents) = 0 THEN [NULL] ELSE dependents END) AS dependent
    OPTIONAL MATCH (dependent)-[edge:{relationship_pattern}]->(child)
    RETURN root.cache_key AS root_cache_key,
           dependent.cache_key AS dependent_cache_key,
           labels(dependent) AS dependent_labels,
           dependent.lifecycle_status AS dependent_lifecycle_status,
           dependent.time_granularity AS dependent_granularity,
           dependent.subject_kind AS dependent_subject_kind,
           dependent.subject_key AS dependent_subject_key,
           type(edge) AS edge_type,
           child.cache_key AS child_cache_key
    ORDER BY dependent_cache_key, edge_type, child_cache_key
    """
    lineage_rows, _ = db.cypher_query(lineage_query, {'cache_key': clean_cache_key})

    root_cache_key, root_labels, root_lifecycle_status, root_granularity, root_subject_kind, root_subject_key = root_rows[0]
    nodes_by_cache_key: dict[str, dict[str, Any]] = {
        str(root_cache_key): {
            'cache_key': root_cache_key,
            'labels': list(root_labels or []),
            'lifecycle_status': root_lifecycle_status,
            'time_granularity': root_granularity,
            'subject_kind': root_subject_kind,
            'subject_key': root_subject_key,
            'edges': [],
        },
    }

    for row in lineage_rows:
        dependent_cache_key = row[1]
        if dependent_cache_key is None:
            continue
        dependent_cache_key_string = str(dependent_cache_key)
        if dependent_cache_key_string not in nodes_by_cache_key:
            nodes_by_cache_key[dependent_cache_key_string] = {
                'cache_key': dependent_cache_key,
                'labels': list(row[2] or []),
                'lifecycle_status': row[3],
                'time_granularity': row[4],
                'subject_kind': row[5],
                'subject_key': row[6],
                'edges': [],
            }
        edge_type = row[7]
        child_cache_key = row[8]
        if edge_type and child_cache_key:
            nodes_by_cache_key[dependent_cache_key_string]['edges'].append(
                {
                    'relationship': edge_type,
                    'target_cache_key': child_cache_key,
                },
            )

    return json_safe_structure(
        {
            'cache_key': clean_cache_key,
            'relationship_types': list(clean_relationship_types),
            'max_depth': int(max_depth),
            'root': nodes_by_cache_key[str(root_cache_key)],
            'dependents': [
                node_payload
                for cache_key_string, node_payload in sorted(nodes_by_cache_key.items())
                if cache_key_string != str(root_cache_key)
            ],
        },
    )
