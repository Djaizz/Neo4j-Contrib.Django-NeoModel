// Batch-fetch period rollup nodes by cache_key (indexed IN lookup).
// Parameters: $keys (list[str])
MATCH (n:`__LABEL__`)
WHERE n.cache_key IN $keys
RETURN n.cache_key AS cache_key, properties(n) AS node_properties
