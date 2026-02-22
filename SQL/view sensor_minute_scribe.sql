CREATE VIEW sensor_minute_scribe AS
SELECT
  minute,
  entity_id,
  COALESCE(
    (SELECT state
     FROM states sma
     WHERE sma.entity_id = base.entity_id
       AND sma.time <= base.minute
     ORDER BY sma.time DESC
     LIMIT 1),
    '0'
  ) AS state
FROM (
  SELECT
    generate_series(
      (SELECT MIN(time) FROM states),
      (SELECT MAX(time) FROM states),
      INTERVAL '1 minute'
    ) AS minute,
    entity_id
  FROM (SELECT DISTINCT entity_id FROM states) entities
) base;
