// Bulk MERGE period rollup nodes by cache_key (ON CREATE only).
// Parameters: $rows (list[dict])
UNWIND $rows AS row
MERGE (n:`__LABEL__` {cache_key: row.cache_key})
ON CREATE SET n = row
