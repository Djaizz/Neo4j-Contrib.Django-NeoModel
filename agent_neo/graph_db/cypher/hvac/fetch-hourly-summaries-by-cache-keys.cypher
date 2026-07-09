// Batch-fetch HourlyHVACPointSummary rows by cache_key (indexed IN lookup).
// Parameters: $keys (list[str])
MATCH (n:`__LABEL__`)
WHERE n.cache_key IN $keys
RETURN
  n.cache_key AS cache_key,
  n.facility_name AS facility_name,
  n.asset_name AS asset_name,
  n.point_name AS point_name,
  n.point_role_uris_csv AS point_role_uris_csv,
  n.point_unit AS point_unit,
  n.local_hour_start AS local_hour_start,
  n.local_hour_end AS local_hour_end,
  n.sample_count AS sample_count,
  n.numeric_sample_count AS numeric_sample_count,
  n.coverage_ratio AS coverage_ratio,
  n.min_value AS min_value,
  n.max_value AS max_value,
  n.mean_value AS mean_value,
  n.first_value_string AS first_value_string,
  n.last_value_string AS last_value_string,
  n.has_numeric_values AS has_numeric_values,
  n.created AS created,
  n.updated AS updated
