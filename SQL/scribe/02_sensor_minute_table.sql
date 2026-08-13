-- ==========================================================================
-- Scribe / TimescaleDB - step 2: the prefilled sensor_minute hypertable
--
-- sensor_minute holds one row per entity per minute, carrying the last known
-- value forward (LOCF) so charts have no gaps. It is a real hypertable that a
-- background job appends to every minute - deliberately NOT a view.
--
-- Why a table and not a view: the LOCF view (sensor_minute_scribe) builds a
-- grid of every minute since the oldest bucket x every entity and runs a
-- correlated subquery per cell against another view, so it has no usable
-- index. On a database with a few hundred entities and months of history that
-- runs into query timeouts, and it gets dramatically worse for entities that
-- were added recently: for every minute before their first reading the
-- subquery has to scan the whole series to prove there is nothing there.
--
-- Run 01_sensor_minute_aggregate.sql first.
--
-- RE-RUNNING ON AN EXISTING INSTALLATION
-- Every statement here is guarded, but the compression ALTER is the one to
-- watch: TimescaleDB refuses to change compression settings once chunks have
-- been compressed. If you only want to update the refresh procedure on a
-- running system, run just the "refresh procedure" section below plus its
-- DROP - that part is self-contained and takes effect on the next job run.
-- ==========================================================================

-- --------------------------------------------------------------------------
-- Table + hypertable
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sensor_minute (
    minute    timestamptz      NOT NULL,
    entity_id text             NOT NULL,
    state     text,
    value     double precision
);

SELECT create_hypertable(
    'public.sensor_minute',
    by_range('minute', INTERVAL '7 days'),
    if_not_exists => true
);

-- The unique index is what makes the ON CONFLICT upsert in the refresh
-- procedure work; the entity index is what makes card queries fast.
CREATE UNIQUE INDEX IF NOT EXISTS sensor_minute_minute_entity_idx
    ON public.sensor_minute (minute, entity_id);
CREATE INDEX IF NOT EXISTS sensor_minute_entity_idx
    ON public.sensor_minute (entity_id, minute DESC);
CREATE INDEX IF NOT EXISTS sensor_minute_minute_idx
    ON public.sensor_minute (minute DESC);

SELECT remove_retention_policy('public.sensor_minute', if_exists => true);
SELECT remove_compression_policy('public.sensor_minute', if_exists => true);

ALTER TABLE public.sensor_minute SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'entity_id',
    timescaledb.compress_orderby = 'minute'
);

SELECT add_compression_policy('public.sensor_minute', INTERVAL '7 days');
SELECT add_retention_policy('public.sensor_minute', INTERVAL '10 years');

-- --------------------------------------------------------------------------
-- The refresh procedure
--
-- It reprocesses a short trailing window instead of only appending after
-- max(minute). The continuous aggregate lags real time by a minute or two, so
-- a row written for "now" often still carries the previous value. Without the
-- overlap those rows are never revisited and the lag becomes permanent, which
-- shows up as counters (utility_meter, Riemann sums) being sampled a couple of
-- minutes too early in every hourly bucket. The ON CONFLICT upsert corrects
-- them on the next pass.
-- --------------------------------------------------------------------------
-- Upgrading from the parameterless version: drop it first. CREATE OR REPLACE
-- with a different argument list creates an *overload* rather than replacing,
-- and CALL sensor_minute_refresh() would keep resolving to the old body.
DROP PROCEDURE IF EXISTS public.sensor_minute_refresh();

CREATE OR REPLACE PROCEDURE public.sensor_minute_refresh(
    p_overlap interval DEFAULT INTERVAL '5 minutes'
)
LANGUAGE plpgsql
AS $procedure$
DECLARE
    v_last_minute    timestamptz;
    v_current_minute timestamptz;
    v_from_minute    timestamptz;
BEGIN
    v_current_minute := date_trunc('minute', now());

    SELECT MAX(minute) INTO v_last_minute FROM public.sensor_minute;

    IF v_last_minute IS NULL THEN
        RAISE NOTICE 'sensor_minute is empty; run the initial backfill first.';
        RETURN;
    END IF;

    -- Start one overlap window back so late aggregate data corrects earlier rows.
    v_from_minute := GREATEST(v_last_minute - p_overlap, v_last_minute - INTERVAL '1 hour');

    IF v_from_minute > v_current_minute THEN
        RETURN;
    END IF;

    INSERT INTO public.sensor_minute (minute, entity_id, state, value)
    SELECT
        m.minute,
        e.entity_id,
        COALESCE(latest.state, '0') AS state,
        COALESCE(
            latest.value,
            CASE
                WHEN latest.state IS NOT NULL
                     AND substring(trim(latest.state) FROM '[-+]?\d+(?:[.,]\d+)?') IS NOT NULL
                THEN REPLACE(
                    substring(trim(latest.state) FROM '[-+]?\d+(?:[.,]\d+)?'),
                    ',', '.'
                )::double precision
                ELSE 0
            END
        ) AS value
    FROM generate_series(v_from_minute, v_current_minute, INTERVAL '1 minute') AS m(minute)
    CROSS JOIN (
        SELECT DISTINCT entity_id FROM public.sensor_minute_aggregate_entity
    ) AS e
    LEFT JOIN LATERAL (
        SELECT sma.state, sma.value
        FROM public.sensor_minute_aggregate_entity sma
        WHERE sma.entity_id = e.entity_id
          AND sma.bucket <= m.minute
        ORDER BY sma.bucket DESC
        LIMIT 1
    ) AS latest ON true
    ON CONFLICT (minute, entity_id) DO UPDATE
        SET state = EXCLUDED.state,
            value = EXCLUDED.value;
END;
$procedure$;

-- Wrapper with the signature the TimescaleDB job runner expects.
CREATE OR REPLACE PROCEDURE public.every_minute_refresh(job_id integer, config jsonb)
LANGUAGE plpgsql
AS $procedure$
BEGIN
    CALL public.sensor_minute_refresh();
END;
$procedure$;

-- Manual trigger, handy for testing.
CREATE OR REPLACE PROCEDURE public.refresh_sensor_minute()
LANGUAGE plpgsql
AS $procedure$
BEGIN
    CALL public.sensor_minute_refresh();
END;
$procedure$;

-- --------------------------------------------------------------------------
-- Schedule it every minute, but only if it is not already scheduled.
--
-- add_job() has no "if not exists": calling it twice gives you two jobs
-- running the same procedure every minute, competing for the same rows. The
-- guard below makes this file safe to re-run on an existing installation.
-- --------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.jobs
        WHERE proc_schema = 'public' AND proc_name = 'every_minute_refresh'
    ) THEN
        PERFORM add_job('public.every_minute_refresh', INTERVAL '1 minute');
        RAISE NOTICE 'every_minute_refresh scheduled every minute.';
    ELSE
        RAISE NOTICE 'every_minute_refresh is already scheduled; leaving it alone.';
    END IF;
END
$$;

-- Inspect or remove the schedule:
--   SELECT job_id, schedule_interval, next_start FROM timescaledb_information.jobs
--    WHERE proc_name = 'every_minute_refresh';
--   SELECT delete_job(job_id) FROM timescaledb_information.jobs
--    WHERE proc_name = 'every_minute_refresh';

-- --------------------------------------------------------------------------
-- Grants. Only needed when the reader integration connects as a different
-- role than the one that created these objects.
-- --------------------------------------------------------------------------
-- GRANT USAGE ON SCHEMA public TO scribe;
-- GRANT SELECT ON public.sensor_minute TO scribe;

-- --------------------------------------------------------------------------
-- Initial fill. The procedure only extends an existing series, so seed the
-- table once before the job can take over.
--
-- MIND THE SIZE. This writes one row per entity per minute:
--
--     entities x days x 1440 = rows
--     443 entities x 30 days x 1440 = ~19 million rows
--
-- in a single transaction. That can run for a long time, bloat the WAL and
-- hold locks meanwhile. Start small - a couple of days - confirm the result,
-- and only then widen. For a long backfill, loop over it a day at a time:
--
--   DO $$
--   DECLARE d date;
--   BEGIN
--     FOR d IN SELECT generate_series(now()::date - 30, now()::date, '1 day')::date
--     LOOP
--       INSERT INTO public.sensor_minute (minute, entity_id, state, value)
--       SELECT m.minute, e.entity_id,
--              COALESCE(latest.state, '0'), COALESCE(latest.value, 0)
--       FROM generate_series(d::timestamptz, d::timestamptz + interval '1 day'
--                            - interval '1 minute', interval '1 minute') AS m(minute)
--       CROSS JOIN (SELECT DISTINCT entity_id
--                     FROM public.sensor_minute_aggregate_entity) AS e
--       LEFT JOIN LATERAL (
--           SELECT sma.state, sma.value
--           FROM public.sensor_minute_aggregate_entity sma
--           WHERE sma.entity_id = e.entity_id AND sma.bucket <= m.minute
--           ORDER BY sma.bucket DESC LIMIT 1
--       ) AS latest ON true
--       ON CONFLICT (minute, entity_id) DO NOTHING;
--       COMMIT;
--       RAISE NOTICE 'day % done', d;
--     END LOOP;
--   END $$;
--
-- Refresh the continuous aggregate first, otherwise there is nothing to carry
-- forward:  CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
--
-- The single-shot version below is fine for a few days of history.
-- --------------------------------------------------------------------------
-- INSERT INTO public.sensor_minute (minute, entity_id, state, value)
-- SELECT m.minute,
--        e.entity_id,
--        COALESCE(latest.state, '0'),
--        COALESCE(latest.value, 0)
-- FROM generate_series(
--          date_trunc('minute', now() - INTERVAL '30 days'),
--          date_trunc('minute', now()),
--          INTERVAL '1 minute'
--      ) AS m(minute)
-- CROSS JOIN (SELECT DISTINCT entity_id FROM public.sensor_minute_aggregate_entity) AS e
-- LEFT JOIN LATERAL (
--     SELECT sma.state, sma.value
--     FROM public.sensor_minute_aggregate_entity sma
--     WHERE sma.entity_id = e.entity_id AND sma.bucket <= m.minute
--     ORDER BY sma.bucket DESC LIMIT 1
-- ) AS latest ON true
-- ON CONFLICT (minute, entity_id) DO NOTHING;
