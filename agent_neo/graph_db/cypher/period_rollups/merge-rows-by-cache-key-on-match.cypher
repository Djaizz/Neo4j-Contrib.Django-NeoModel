// Bulk MERGE period rollup nodes; refresh properties on match when recomputing.
// Parameters: $rows (list[dict])
//
// `row` carries a fresh `created`/`updated` (neo4j_bulk_timestamps). We snapshot
// the pre-existing `created` BEFORE writing `row`, then restore it via coalesce so
// `updated` is bumped on every match while the original `created` is preserved
// (audit invariant). On create the snapshot is null, so `created` becomes row.created.
UNWIND $rows AS row
MERGE (n:`__LABEL__` {cache_key: row.cache_key})
WITH n, row, n.created AS existing_created
SET n += row, n.created = coalesce(existing_created, row.created)
