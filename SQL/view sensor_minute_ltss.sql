CREATE VIEW sensor_minute_ltss AS
SELECT
  minute,
  entity_id,
  COALESCE(
    (SELECT state
     FROM sensor_minute_aggregate sma
     WHERE sma.entity_id = base.entity_id
       AND sma.bucket <= base.minute
     ORDER BY sma.bucket DESC
     LIMIT 1),
    0
  ) AS state
FROM (
  SELECT
    generate_series(
      (SELECT MIN(bucket) FROM sensor_minute_aggregate),
      (SELECT MAX(bucket) FROM sensor_minute_aggregate),
      INTERVAL '1 minute'
    ) AS minute,
    entity_id
  FROM (SELECT DISTINCT entity_id FROM sensor_minute_aggregate) entities
) base;