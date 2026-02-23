-- TimescaleDB SQL (Scribe)
-- Continuous aggregate with 1-minute buckets per entity
-- Source table: states (columns: time, entity_id, state, value)
-- Aggregate view: sensor_minute_aggregate

DROP MATERIALIZED VIEW IF EXISTS sensor_minute_aggregate;

CREATE MATERIALIZED VIEW sensor_minute_aggregate
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 minute', s.time) AS bucket,
  s.entity_id,
  last(s.state, s.time) AS state,
  last(s.value, s.time) AS value
FROM states s
GROUP BY bucket, entity_id
WITH NO DATA;

-- Remove existing policies (safe to re-run policy setup)
SELECT remove_continuous_aggregate_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_retention_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_compression_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_retention_policy('states', if_exists => true);
SELECT remove_compression_policy('states', if_exists => true);

-- Enable compression before adding compression policies
ALTER MATERIALIZED VIEW sensor_minute_aggregate
SET (
  timescaledb.compress = true,
  timescaledb.compress_segmentby = 'entity_id',
  timescaledb.compress_orderby = 'bucket'
);

ALTER TABLE states
SET (
  timescaledb.compress = true,
  timescaledb.compress_segmentby = 'entity_id',
  timescaledb.compress_orderby = 'time'
);

-- Refresh policy must exist before compression policy on continuous aggregate
SELECT add_continuous_aggregate_policy(
  'sensor_minute_aggregate',
  start_offset => INTERVAL '2 months',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '5 minutes'
);

-- Retention and compression policies
SELECT add_retention_policy('sensor_minute_aggregate', INTERVAL '10 years');
SELECT add_compression_policy('sensor_minute_aggregate', INTERVAL '3 months');
SELECT add_retention_policy('states', INTERVAL '3 months');
SELECT add_compression_policy('states', INTERVAL '3 months');

-- Optional manual backfill (run separately with autocommit, not in a transaction block)
-- CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
