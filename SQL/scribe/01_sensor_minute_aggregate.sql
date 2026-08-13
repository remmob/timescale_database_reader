-- ==========================================================================
-- Scribe / TimescaleDB - step 1: 1-minute continuous aggregate
--
-- Current Scribe schema (2026):
--   states_raw   hypertable (time, metadata_id, state, value, attributes)
--   entities     lookup table (id, entity_id, unique_id, platform, domain, ...)
--   states       view that joins the two and exposes entity_id
--
-- states_raw stores metadata_id, not entity_id, so the aggregate groups by
-- metadata_id and a thin view adds the entity_id back. Grouping the join
-- directly is not possible: a continuous aggregate may only read a single
-- hypertable.
--
-- REQUIREMENTS
--   TimescaleDB 2.13 or newer. 02_sensor_minute_table.sql uses the by_range()
--   dimension builder, which does not exist before 2.13.
--   Scribe must already be installed AND have written data: this aggregate
--   reads states_raw, and step 2 produces nothing while it is empty.
--
-- ROLES
--   Run as a role that may create objects in the target database. If Scribe
--   connects as a different role than the reader integration, see the GRANT
--   section at the bottom - without it the reader gets "permission denied".
--
-- Run this file first, then 02_sensor_minute_table.sql.
-- ==========================================================================

-- --------------------------------------------------------------------------
-- The aggregate itself: one row per entity per minute, last known value.
-- --------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_minute_aggregate
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute'::interval, sr.time) AS bucket,
    sr.metadata_id,
    last(sr.state, sr.time)                    AS state,
    last(sr.value, sr.time)                    AS value
FROM states_raw sr
GROUP BY 1, 2
WITH NO DATA;

-- --------------------------------------------------------------------------
-- entity_id lookup on top of the aggregate. Everything downstream reads this
-- view, never the aggregate directly.
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW sensor_minute_aggregate_entity AS
SELECT
    a.bucket,
    e.entity_id,
    a.state,
    a.value
FROM sensor_minute_aggregate a
JOIN entities e ON e.id = a.metadata_id;

-- --------------------------------------------------------------------------
-- Policies. Safe to re-run: every policy is dropped first.
-- --------------------------------------------------------------------------
SELECT remove_continuous_aggregate_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_retention_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_compression_policy('sensor_minute_aggregate', if_exists => true);
SELECT remove_retention_policy('states_raw', if_exists => true);
SELECT remove_compression_policy('states_raw', if_exists => true);

ALTER MATERIALIZED VIEW sensor_minute_aggregate SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'metadata_id',
    timescaledb.compress_orderby = 'bucket'
);

ALTER TABLE states_raw SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'metadata_id',
    timescaledb.compress_orderby = 'time'
);

-- Refresh every minute. end_offset 0 keeps the aggregate current right up to
-- now; start_offset 2 minutes re-materializes the trailing two minutes so
-- states that arrive late are still picked up.
SELECT add_continuous_aggregate_policy(
    'sensor_minute_aggregate',
    start_offset     => INTERVAL '2 minutes',
    end_offset       => INTERVAL '0',
    schedule_interval => INTERVAL '1 minute'
);

-- Raw states are the bulky part: keep 3 months. The minute aggregate is small
-- enough to keep for 10 years.
--
-- add_compression_policy is the classic name. TimescaleDB 2.18+ also ships
-- add_columnstore_policy and reports these jobs as "Columnstore Policy"; the
-- old name still works and is kept here for compatibility with older servers.
SELECT add_retention_policy('sensor_minute_aggregate', INTERVAL '10 years');
SELECT add_compression_policy('sensor_minute_aggregate', INTERVAL '3 months');
SELECT add_retention_policy('states_raw', INTERVAL '3 months');
SELECT add_compression_policy('states_raw', INTERVAL '3 months');

-- --------------------------------------------------------------------------
-- Grants. Only needed when the reader integration (and/or Scribe) connects as
-- a different role than the one that created these objects. Replace the role
-- name with whatever your reader connection uses.
-- --------------------------------------------------------------------------
-- GRANT USAGE ON SCHEMA public TO scribe;
-- GRANT SELECT ON sensor_minute_aggregate        TO scribe;
-- GRANT SELECT ON sensor_minute_aggregate_entity TO scribe;
-- GRANT SELECT ON entities                       TO scribe;

-- --------------------------------------------------------------------------
-- One-time backfill of everything already in states_raw.
-- Run this OUTSIDE a transaction block (psql: \set AUTOCOMMIT on).
-- --------------------------------------------------------------------------
-- CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
