// Preload electricity meter period rollups for aggregation (populate / bulk create).
// Parameters: spine_window_where params (facility_name, time_granularity, local_period_start_*)
MATCH (n:`__LABEL__`)
WHERE n.facility_name = $facility_name
  AND n.time_granularity = $time_granularity
  AND n.local_period_start >= $local_period_start_gte
  AND n.local_period_start < $local_period_start_lt
RETURN
  n.cache_key AS cache_key,
  n.facility_name AS facility_name,
  n.meter_asset_name AS meter_asset_name,
  n.time_granularity AS time_granularity,
  n.local_period_start AS local_period_start,
  n.local_period_end AS local_period_end,
  n.kwh AS kwh,
  n.sample_count AS sample_count,
  n.numeric_sample_count AS numeric_sample_count,
  n.coverage_ratio AS coverage_ratio,
  n.has_numeric_values AS has_numeric_values,
  n.point_name AS point_name,
  n.point_unit AS point_unit,
  n.point_role_uri AS point_role_uri,
  n.calculation_method AS calculation_method
