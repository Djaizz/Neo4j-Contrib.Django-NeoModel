// Preload period rollup property maps for a facility-local spine window.
// Parameters: facility_name, temporal_granularity, local_period_start_gte, local_period_start_lt
MATCH (n:`__LABEL__`)
WHERE n.facility_name = $facility_name
  AND n.temporal_granularity = $temporal_granularity
  AND n.local_period_start >= $local_period_start_gte
  AND n.local_period_start < $local_period_start_lt
RETURN n.cache_key AS cache_key, properties(n) AS node_properties
