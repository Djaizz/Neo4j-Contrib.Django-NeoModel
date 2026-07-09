// Count nodes whose $property_name is in $keys (chunked invalidation).
// Parameters: $keys (list[str])
// Label and property are fixed at load time via __LABEL__ / __PROPERTY__ placeholders.
MATCH (n:`__LABEL__`)
WHERE n.__PROPERTY__ IN $keys
RETURN count(n) AS node_count
