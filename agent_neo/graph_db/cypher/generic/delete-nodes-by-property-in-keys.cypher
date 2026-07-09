// Delete nodes whose $property_name is in $keys.
// Parameters: $keys (list[str])
MATCH (n:`__LABEL__`)
WHERE n.__PROPERTY__ IN $keys
DETACH DELETE n
