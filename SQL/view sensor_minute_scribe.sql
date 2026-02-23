DROP VIEW IF EXISTS public.sensor_minute_scribe;

CREATE VIEW public.sensor_minute_scribe AS
SELECT
  base.minute,
  base.entity_id,
  COALESCE(
    (
      SELECT sma.state
      FROM sensor_minute_aggregate sma
      WHERE sma.entity_id = base.entity_id
        AND sma.bucket <= base.minute
      ORDER BY sma.bucket DESC
      LIMIT 1
    ),
    '0'
  ) AS state,
  COALESCE(
    (
      SELECT
        COALESCE(
          sma.value,
          CASE
            WHEN substring(TRIM(sma.state) from '[-+]?\d+(?:[\.,]\d+)?') IS NOT NULL
              THEN REPLACE(substring(TRIM(sma.state) from '[-+]?\d+(?:[\.,]\d+)?'), ',', '.')::double precision
            ELSE NULL
          END
        )
      FROM sensor_minute_aggregate sma
      WHERE sma.entity_id = base.entity_id
        AND sma.bucket <= base.minute
      ORDER BY sma.bucket DESC
      LIMIT 1
    ),
    0
  ) AS value
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

GRANT SELECT ON TABLE public.sensor_minute_scribe TO scribe;
