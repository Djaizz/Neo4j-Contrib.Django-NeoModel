// Delete period rollups in a scope-local window (populate window invalidation).
// Parameters: $scope_name, $start_token, $end_token
// Note: n.facility_name is the legacy on-disk property; the bind param is scope_name.
MATCH (n:`__LABEL__`)
WHERE n.facility_name = $scope_name
  AND n.local_period_start >= $start_token
  AND n.local_period_start < $end_token
DETACH DELETE n
