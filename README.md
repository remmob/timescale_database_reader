[![en](https://img.shields.io/badge/lang-en-red.svg)](README.md)
[![nl](https://img.shields.io/badge/lang-nl-orange.svg)](README.nl.md)

![Version](https://img.shields.io/github/v/release/remmob/timescale_database_reader 'Release') ![Downloads](https://img.shields.io/github/downloads/remmob/timescale_database_reader/total 'Downloads')

# Timescale Database Reader

A Home Assistant integration that reads historical data from a TimescaleDB database filled by the [LTSS integration](https://github.com/freol35241/ltss) or the [Scribe integration](https://github.com/jonathan-gatard/scribe), and exposes it over the Home Assistant WebSocket API.

This integration does **not** work with arbitrary TimescaleDB databases; the schema has to match LTSS or Scribe. If you need another schema, open an issue or contribute a reader for it.

Companion card: [timescale-plotly-card](https://github.com/remmob/timescale-plotly-card).

---

## Supported databases

| Source | Hypertable | Notes |
|--------|-----------|-------|
| **LTSS** | `ltss` | Columns `time`, `entity_id`, `state`. No numeric column. |
| **Scribe** | `states_raw` | Columns `time`, `metadata_id`, `state`, `value`, `attributes`. `entity_id` lives in the separate `entities` table; the `states` view joins the two. |

> **Scribe schema note:** current Scribe versions write `states_raw` keyed on `metadata_id`, not `entity_id`. `states` is a view over `states_raw` joined with `entities`. Anything that has to be fast should read a minute table rather than that view.

### state vs value

Numbers and text live in different columns, and this trips people up:

| | Numeric sensor | Text sensor (`on`/`off`, `Cooling in progress`, …) |
|---|---|---|
| `states_raw.value` | the number (`23.24`) | `0` |
| `states_raw.state` | `NULL` | the text |
| `sensor_minute.value` | the number (`23.24`) | `0` |
| `sensor_minute.state` | `'0'` | the text |

For a numeric entity only `value` carries the reading. In `sensor_minute` the `state` column additionally shows the literal string `'0'` rather than `NULL`, because the fill procedure substitutes `COALESCE(latest.state, '0')`.

So anything consuming this data must read `value` — or the `avg_state` field of the query response, which already resolves it — and fall back to `state` only for text entities. **Reading `state` first flattens every numeric series to zero**, and because `'0'` parses as a perfectly valid number, nothing errors: you just get a chart full of zeroes.

---

## Requirements

| | |
|---|---|
| **TimescaleDB** | 2.13 or newer. The SQL uses `by_range()`, which does not exist before 2.13 |
| **PostgreSQL** | 14 or newer |
| **Scribe or LTSS** | installed **and already recording**, before you run any of the SQL |
| **Database role** | one that may create tables, views and jobs in the target database |

## Install order

The steps depend on each other; doing them out of order is the most common way
to end up with empty charts.

1. Install Scribe (or LTSS) and let it record for a few minutes, so `states_raw` has data
2. Run `SQL/scribe/01_sensor_minute_aggregate.sql`, then backfill the aggregate
3. Run `SQL/scribe/02_sensor_minute_table.sql`, then seed `sensor_minute`
4. Install this integration and add a connection, with `table` set to `sensor_minute`
5. Install the [card](https://github.com/remmob/timescale-plotly-card) and build a chart

Step 4 does not verify that the table exists — the connection test only runs
`SELECT 1` — so you can fill it in before or after, but nothing will chart until
steps 2 and 3 are done.

## Installation

### HACS (recommended)

1. HACS → ⋮ → Custom repositories (older HACS versions: HACS → Integrations → ⋮)
2. URL: `https://github.com/remmob/timescale_database_reader`, category: Integration
3. Search for **Timescale Database Reader**, install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/timescale_database_reader` into your Home Assistant `custom_components` directory
2. Restart Home Assistant

### Configuration

**Settings → Devices & Services → Add Integration → Timescale Database Reader**, then fill in host, port, username, password, database name and the default table.

| Field | Example | Meaning |
|-------|---------|---------|
| `host` / `port` | `192.168.1.10` / `5432` | TimescaleDB server |
| `database` | `statistics` | Database name |
| `name` | `Statistics` | Friendly name; also what `database:` in a card matches on |
| `table` | `sensor_minute` | Default table when a query does not pass `table` |
| `include_extra_columns` | `false` | Also return the remaining columns of the queried table. Off by default — see [Extra columns](#extra-columns-opt-in) |

Add one integration entry per database if you have several (for example LTSS **and** Scribe).

> **Two places hold these settings.** The integration reads `{**entry.data, **entry.options}`, so anything set through the *options* dialog wins over what you entered when first adding the connection. If a changed table does not seem to take effect, check both — reconfigure updates `data`, the options flow writes `options`.

### Database roles and grants

If the role that creates the SQL objects is the same one the integration connects with, there is nothing to do. If they differ — which happens easily when an admin runs the SQL as `postgres` while Scribe and the reader use their own roles — the reader will fail with *permission denied*. Both SQL files end with a commented grant block; uncomment it and substitute your role:

```sql
GRANT USAGE ON SCHEMA public TO <reader_role>;
GRANT SELECT ON sensor_minute, sensor_minute_aggregate_entity, entities TO <reader_role>;
```

Check who owns what with:

```sql
SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'
UNION ALL
SELECT viewname, viewowner FROM pg_views WHERE schemaname = 'public' ORDER BY 1;
```

> **Matching a card to a connection:** a card's `database:` option is matched case-insensitively against both the entry's *database name* and its *friendly name*. `database: scribe` only resolves to a connection literally called `scribe`; otherwise the first configured connection is used as a fallback. Name the entry after what you write in your cards to avoid surprises.

---

## Recommended: build the minute tables

Charts want one value per entity per minute, with the last known value carried forward so lines and bars have no gaps. Raw state rows cannot give you that: Home Assistant only writes a row when a value changes.

Two layers do this. Install them in order.

### Step 1 — the 1-minute continuous aggregate

`SQL/scribe/01_sensor_minute_aggregate.sql`

Creates `sensor_minute_aggregate` (one row per entity per minute in which something changed) plus `sensor_minute_aggregate_entity`, a thin view that joins `entities` back on so downstream queries can use `entity_id`. It also sets the retention and compression policies and a refresh policy that runs every minute.

The aggregate has to group by `metadata_id`, because a continuous aggregate may only read one hypertable — it cannot join `entities` itself. That is what the extra view is for.

After creating it, backfill the history you already have. Run this **outside** a transaction block:

```sql
CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
```

### Step 2 — the prefilled `sensor_minute` table

`SQL/scribe/02_sensor_minute_table.sql`

Creates the `sensor_minute` hypertable (`minute`, `entity_id`, `state`, `value`), its indexes, its policies, the `sensor_minute_refresh()` procedure, and a job that runs it every minute. Each run carries the last known value forward for every entity for every minute.

Seed the table once before the job can take over — the procedure only extends an existing series and does nothing on an empty table. The commented-out `INSERT` at the bottom of the file does that.

> **Start small.** The seed writes one row per entity per minute: `entities × days × 1440`. With 443 entities and 30 days that is roughly **19 million rows in one transaction**, which can run for a long time, bloat the WAL and hold locks while it does. Seed a couple of days first, confirm your charts look right, and only then widen. The file also contains a day-at-a-time loop that commits per day — use that for a long backfill.

Check that the job is running:

```sql
SELECT job_id, proc_name, schedule_interval, next_start
FROM timescaledb_information.jobs
WHERE proc_name = 'every_minute_refresh';

SELECT last_run_status, last_run_started_at, total_failures
FROM timescaledb_information.job_stats
WHERE job_id = (SELECT job_id FROM timescaledb_information.jobs
                WHERE proc_name = 'every_minute_refresh');
```

### Which table should a card use?

| Table | Speed | When to use |
|-------|-------|-------------|
| **`sensor_minute`** | fast, indexed on `(entity_id, minute DESC)` | **The default choice.** Every chart, every range. |
| `sensor_minute_aggregate_entity` | fast | When you want only the minutes in which something actually changed, without the carried-forward filler. |
| `states_raw` / `ltss` | moderate | Raw, unaggregated history. |
| `states` | slow | Avoid for charts; it is a view that joins on every read. |
| `sensor_minute_scribe` | **very slow** | Legacy LOCF view, superseded by `sensor_minute`. See the warning below. |

```yaml
type: custom:timescale-plotly-card
database: statistics
table: sensor_minute
sensor_id: sensor.temperature_woonkamer
```

> **⚠️ Avoid `sensor_minute_scribe` (and `sensor_minute_ltss`).** These views build a grid of every minute since the oldest bucket × every entity and run a correlated subquery per cell against another view, so there is no usable index. It gets pathological for recently added entities: for every minute before their first reading the subquery has to walk the entire series to prove there is nothing there, so a window reaching further back than that entity's first reading times out (>120 s) while a window starting after it returns instantly. One such entity is enough to stall the queries of other cards on the same page. The `sensor_minute` table exists precisely to avoid this. The old files are kept in `SQL/` for reference.

### Disk usage

Raw state rows are the bulky part. Every row carries the entity's attributes as
JSON — icon, friendly name, unit — repeated in full on each write. On a real
installation that was 154 of roughly 205 bytes of payload per row.

Compression fixes most of it. Measured on 443 entities writing about a million
rows a day:

| | before | after |
|---|---|---|
| One weekly `states_raw` chunk | 300 MB | 8.9 MB |
| Thirteen older chunks | 383 MB | 16 MB |
| `sensor_minute` (LOCF data compresses extremely well) | 10.9 GB | 22 MB |

**Set `compress_after` well below `drop_after`.** If they are equal — both three
months, say — the retention policy deletes each chunk at the exact moment it
becomes eligible for compression, so nothing is ever compressed and the policy
does nothing at all. The SQL here uses seven days.

Check whether it is actually working:

```sql
SELECT hypertable_name,
       count(*) FILTER (WHERE is_compressed) AS compressed,
       count(*) AS chunks
FROM timescaledb_information.chunks GROUP BY 1;
```

Only the chunk currently being written to should show up as uncompressed. If
that chunk itself is large, shorten `chunk_time_interval`: the active chunk
cannot be compressed, so its interval sets the floor on your uncompressed
working set.

Compression is a storage format change, not a summarisation: row counts, values
and timestamps are unchanged, and `decompress_chunk()` reverses it.

### Keeping the minute table in step with reality

The continuous aggregate trails real time by a minute or two. If the refresh procedure only ever appends rows *after* `max(minute)`, those trailing rows keep the value they happened to have when they were written and are never corrected — the lag becomes permanent.

You notice it on counters. A `utility_meter` with `cycle: hourly` resets exactly at `:00`, but in a lagging `sensor_minute` the reset only shows up two minutes later. A chart that buckets on the clock hour then samples each hour a couple of minutes too early, so every bar under-reports and the tail of each period lands in the next bar.

`sensor_minute_refresh()` therefore reprocesses a short trailing window (5 minutes by default) instead of only appending, and upserts on `(minute, entity_id)`. Pass a different overlap if your setup needs it:

```sql
CALL public.sensor_minute_refresh(INTERVAL '10 minutes');
```

Check the lag with:

```sql
SELECT max(minute) AS last_row,
       date_trunc('minute', now()) AS now_minute,
       date_trunc('minute', now()) - max(minute) AS lag
FROM sensor_minute;
```

---

## Querying over the WebSocket API

Message type: `timescale/query`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sensor_id` | string | **yes** | Entity ID to query |
| `start` | ISO string or Unix timestamp | **yes** | Window start |
| `end` | ISO string or Unix timestamp | **yes** | Window end |
| `limit` | int | no | Max rows returned (0 = no limit, max 10000). Applied to the tail of the result |
| `downsample` | int | no | Bucket size in seconds (0 = raw rows) |
| `downsample_method` | `avg` \| `last` \| `sum` | no | Aggregation within a bucket. Defaults to `last` for minute/aggregate tables, otherwise `avg`. Use `sum` for rows that are already a quantity per bucket — a cost or a number of kWh per hour — so that a query for daily buckets adds those hours up instead of averaging them or taking the last one |
| `table` | string | no | Table or view to read; falls back to the entry's configured table |
| `database` | string | no | Which connection to use, matched on database name or friendly name |
| `entry_id` | string | no | Config entry to use; takes precedence over `database` |

Limits enforced by the integration: window ≤ 365 days, `limit` ≤ 10000, result ≤ 50000 rows.

The reader picks the time column automatically: `time`, else `bucket`, else `minute`. If the table has a `value` column it is preferred, with a numeric cast of `state` as fallback.

### Response

With `downsample > 0`:

| Field | Description |
|-------|-------------|
| `bucket` | Bucket start |
| `avg_state` | Aggregated numeric value (`avg()` or `last()`) — **use this** |
| `state` | Last raw text state in the bucket |
| `min_state` / `max_state` | Numeric min and max within the bucket |

With `downsample = 0`:

| Field | Description |
|-------|-------------|
| `time` | Row timestamp |
| `state` | Raw text state |
| `avg_state` | Resolved numeric value — **use this** |

> Remember the `state` / `value` split above: for numeric entities `state` is the placeholder `'0'`. Always read `avg_state`, and fall back to `state` only when you are mapping text states.

### Extra columns (opt in)

The response set above is fixed. Query a view that carries columns of its own — a label, a unit, a
formatted timestamp — and those columns are dropped, because the reader never selected them.

Enable **Include extra columns** on the config entry and every remaining column of the queried table
comes along. Reserved names are never selected twice: `entity_id`, `value`, `state`, `time`,
`bucket` and `minute` are already handled by the query itself.

```sql
-- with downsample > 0, each extra column is wrapped in last() so GROUP BY stays valid
SELECT time_bucket(:bucket, bucket) AS bucket,
       last(value, bucket)  AS avg_state,
       last(state, bucket)  AS state,
       min(value)           AS min_state,
       max(value)           AS max_state,
       last("label", bucket) AS "label",
       last("unit",  bucket) AS "unit"
FROM my_view
WHERE entity_id = :entity_id AND bucket BETWEEN :start AND :end
GROUP BY bucket
```

Points to keep in mind:

- **Off by default.** With the option disabled the generated SQL is character for character what it
  was before, so existing dashboards cannot be affected.
- **The setting is per config entry, not per table.** Switch it on and *every* table queried through
  that connection returns its extra columns. For plain state tables that changes nothing: a table
  whose columns are only `time`/`minute`, `entity_id`, `state` and `value` has no remaining columns.
- **No injection risk.** Column names come from `information_schema` through `_fetch_table_columns`,
  so they are by definition real columns of that table. They are quoted as well, so names with
  capitals or spaces are safe.
- **Charts ignore unknown keys.** Only a table view will show the extra columns. Note that in the
  timescale-plotly-card `table_columns` *orders* the columns rather than filtering them: anything
  not listed is appended at the end.

#### Use case: daily peaks as a readable table

The question was simple enough: what was the highest load today, when did it happen, and how long
did it last? A peak of one second says nothing, so the duration matters as much as the value.

All of that is a query, not a state machine — the raw states are already in the database. A daily
table holds one row per sensor per day: highest value, the moment the peak *started*, the moment the
value itself topped out, and how long it stayed within a small margin of the peak. A view then
presents those rows per sensor, with the readable bits as their own columns:

```sql
CREATE OR REPLACE VIEW sensor_extremes_single AS
SELECT (day::timestamp AT TIME ZONE 'Europe/Amsterdam') AS bucket,
       entity_id || '_max' AS entity_id,
       max_value           AS value,
       max_value::text     AS state,
       label                                                   AS sensor,
       round(max_value::numeric, 2) || ' ' || unit             AS waarde,
       to_char(max_start AT TIME ZONE 'Europe/Amsterdam',
               'HH24:MI:SS')                                   AS tijd,
       max_episode_s || ' s'                                   AS duur
FROM sensor_extremes_daily JOIN sensor_extremes_config USING (entity_id);
```

Two details that are easy to get wrong:

- **Cast the day in the right time zone.** A plain `day::timestamptz` on a server running UTC lands
  on midnight UTC, which shows up as 02:00 in a Dutch frontend. `AT TIME ZONE` fixes it and handles
  DST along the way.
- **A value holds until the next reading.** Home Assistant only writes on change, so a duration is
  the gap between two readings (`lead(time)`), never a count of rows.

With **Include extra columns** enabled, the card can show those columns directly:

```yaml
type: custom:timescale-plotly-card
database: scribe
table: sensor_extremes_single
show_chart: false
show_table: true
table_columns: [sensor, waarde, tijd, duur]
energy_time_ranges: [today, week, month, year, years, custom]
default_range: today
entities:
  - sensor_id: sensor.power_inuse_total_max
    name: Total power in use
  - sensor_id: sensor.dsmr_sensor_voltage_l1_max
    name: Voltage L1 highest
```

| sensor | waarde | tijd | duur |
|---|---|---|---|
| Gebruikt vermogen totaal | 4063 W | 17:45:57 | 6 s |
| Spanning L1 hoogste | 244.9 V | 10:30:56 | 183 s |
| Spanning L1 laagste | 232.5 V | 10:52:12 | 35 s |

The card still adds `series`, `bucket`, `avg_state`, `state`, `min_state` and `max_state` of its
own, and `table_columns` does not filter those away. Put the four you want first and hide the rest
with card-mod:

```yaml
card_mod:
  style: |
    .ts-data-table td:nth-child(n+5),
    .ts-data-table th:nth-child(n+5) { display: none !important; }
    .ts-data-table td, .ts-data-table th { white-space: normal !important; }
```

That last line matters too: the card sets `white-space: nowrap` on every cell and `overflow-x: auto`
on the container, so one long cell is enough to produce a horizontal scrollbar.

### Example

```python
import asyncio, json, websockets

async def query_timescale():
    uri = "ws://homeassistant.local:8123/api/websocket"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "auth", "access_token": "YOUR_LONG_LIVED_TOKEN"}))
        print(await ws.recv())

        await ws.send(json.dumps({
            "id": 1,
            "type": "timescale/query",
            "sensor_id": "sensor.temperature_woonkamer",
            "database": "statistics",
            "table": "sensor_minute",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T12:00:00Z",
            "downsample": 300,
            "downsample_method": "last",
        }))
        while True:
            msg = await ws.recv()
            print(msg)
            if '"result"' in msg or '"error"' in msg:
                break

asyncio.run(query_timescale())
```

---

## Multiple databases

Add one integration entry per database. Cards select a connection per card or per series:

```yaml
type: custom:timescale-plotly-card
title: Living room climate
entities:
  - sensor_id: sensor.temperature_woonkamer
    database: statistics
    table: sensor_minute
  - sensor_id: sensor.amber_4h_average_ambient_temperature
    database: ltss
    table: ltss
```

A series-level `database` or `table` overrides the card-level one. Without either, the first configured connection and its default table are used.

---

## Troubleshooting

**"No database connection available"** — no config entry is loaded. Check the integration page for a failed entry.

**Every series is flat zero** — something is reading `state` instead of `value`/`avg_state`. See [state vs value](#state-vs-value).

**Queries time out** — you are almost certainly on `sensor_minute_scribe` or `states`. Switch to `table: sensor_minute`. If that is also slow, verify `sensor_minute_entity_idx` exists.

**A newly added entity has no history** — `sensor_minute` only starts at the point the entity first appeared in the aggregate. Re-run the backfill after `CALL refresh_continuous_aggregate(...)`.

**Counters look a couple of minutes off** — see [Keeping the minute table in step with reality](#keeping-the-minute-table-in-step-with-reality).

**Nothing at all comes back** — the reader logs every query at warning level with prefix `[WEBSOCKET]`. Check the Home Assistant log.

---

## Issues & contributions

Open an issue or pull request on [GitHub](https://github.com/remmob/timescale_database_reader).

---
©2026 Bommer Software | Author: Mischa Bommer

> **Note:** This integration is a work in progress. Features and functionality may change or be incomplete.
