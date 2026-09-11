// Existing rollup cache keys in a scope-local spine window.
// Parameters: scope_name, temporal_granularity, local_period_start_gte, local_period_start_lt
// Note: n.facility_name is the legacy on-disk property; the bind param is scope_name.
MATCH (n:`__LABEL__`)
WHERE n.facility_name = $scope_name
  AND n.temporal_granularity = $temporal_granularity
  AND n.local_period_start >= $local_period_start_gte
  AND n.local_period_start < $local_period_start_lt
RETURN n.cache_key AS cache_key
