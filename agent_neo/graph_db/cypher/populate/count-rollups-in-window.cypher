// Count period rollups in a facility-local window (populate force_redo).
// Parameters: $facility_name, $start_token, $end_token
MATCH (n:`__LABEL__`)
WHERE n.facility_name = $facility_name
  AND n.local_period_start >= $start_token
  AND n.local_period_start < $end_token
RETURN count(n) AS node_count
