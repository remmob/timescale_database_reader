# Timescale Database Reader

A Home Assistant integration for reading historical data from a TimescaleDB database that is filled by the [LTSS integration](https://github.com/freol35241/ltss) or the [Scribe integration](https://github.com/jonathan-gatard/scribe). This integration does **not** work with arbitrary TimescaleDB databases; the schema and data must match that of LTSS or Scribe.
If you need a different database schema reach out to the author or consider contributing a new database reader for your specific schema.

## Supported Databases
This integration is designed specifically for TimescaleDB databases that are populated by:
- **LTSS** (Long Term Statistics Store) — table: `ltss`
- **Scribe** — table: `states`


## Recommended Views

For optimal charting and uninterrupted lines, it is recommended to install the following SQL views and aggregates in your TimescaleDB:

- For LTSS:
    - Continuous aggregate: `sensor_minute_aggregate` (see `SQL/sensor_minute_aggregate_ltss.sql`)
    - Prefilled view: `sensor_minute_ltss` (see `view sensor_minute_ltss.sql`)
- For Scribe:
    - Continuous aggregate: `sensor_minute_aggregate` (see `SQL/sensor_minute_aggregate_scribe.sql`)
    - Prefilled view: `sensor_minute_scribe` (see `view sensor_minute_scribe.sql`)<br/><br/>

- to aggerate older data into 1-minute buckets run one time the following SQL 
```sql
CALL refresh_continuous_aggregate('sensor_minute_aggregate', NULL, NULL);
```

The aggregate views generate efficient 1-minute buckets per entity, and the prefilled views create a minute-prefilled time series for each entity, allowing smooth line and bar charts without gaps. Use the `table` option in your card or query to select the appropriate view.

Example for LTSS:
```yaml
type: custom:timescale-plotly-card
sensor_id: sensor.temperature_woonkamer
database: ltss
table: sensor_minute_ltss
```

Example for Scribe:
```yaml
type: custom:timescale-plotly-card
sensor_id: sensor.amber_4h_average_ambient_temperature
database: scribe
table: sensor_minute_scribe
```
You can find the SQL files for creating these views in the `SQL` directory of this repository. Make sure to run the appropriate SQL scripts in your TimescaleDB to set up these views before using them in your Home Assistant cards or queries.


## Example: Query via WebSocket API

You can use the Home Assistant WebSocket API to query TimescaleDB data directly. Here is an example using Python and the `websockets` library:

```python
import asyncio
import websockets
import json

async def query_timescale():
    uri = "ws://homeassistant.local:8123/api/websocket"  # Change to your Home Assistant URL
    async with websockets.connect(uri) as ws:
        # Authenticate (replace with your long-lived access token)
        await ws.send(json.dumps({"type": "auth", "access_token": "YOUR_LONG_LIVED_TOKEN"}))
        print(await ws.recv())  # Auth response

        # Send the query
        await ws.send(json.dumps({
            "id": 1,
            "type": "timescale/query",
            "sensor_id": "sensor.temperature_woonkamer",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T12:00:00Z",
            "limit": 1000,
            "downsample": 0
        }))
        # Receive the result
        while True:
            msg = await ws.recv()
            print(msg)
            if 'result' in msg or 'error' in msg:
                break

asyncio.run(query_timescale())
```

Replace `YOUR_LONG_LIVED_TOKEN` with your Home Assistant long-lived access token. The response will contain the queried data as JSON.

## Visualization: Plotly Card
A special Home Assistant card has been developed to work with this integration: [timescale-plotly-card](https://github.com/remmob/timescale-plotly-card). This allows you to easily create charts from your TimescaleDB data in the Home Assistant dashboard.

## Multiple Database Support

This integration supports connecting to multiple TimescaleDB databases at the same time, as long as each is filled by LTSS or Scribe. You can add multiple database connections via the Home Assistant UI (each as a separate integration instance).

When querying data (for example, from a custom card or via the WebSocket API), you can specify which database to use by passing the `database` parameter. If you do not specify a database, the first configured database will be used by default.

> **Important:** For Scribe, prefer `table: sensor_minute_scribe` (or `sensor_minute_aggregate`) after installing the SQL views. For LTSS, use `table: sensor_minute_ltss` (or `sensor_minute_aggregate`). Use raw tables (`states`/`ltss`) only when you explicitly need non-prefilled raw data.

### Example: Querying a specific database and table

```yaml
# Example for a custom card or direct WebSocket query
 type: custom:timescale-plotly-card
 database: scribe
 sensor_id: sensor.amber_4h_average_ambient_temperature
```

```yaml
 type: custom:timescale-plotly-card
 database: ltss
 sensor_id: sensor.temperature_woonkamer
```

If you use multiple databases in one card (e.g., with multiple series), set the `database` and `table` options for each series as needed. See the wiki for the [Timescale Plotly Card](https://github.com/remmob/timescale-plotly-card/wiki/Timescale-Plotly-Card-Wiki) for more details on how to configure multiple series with different databases.

## Installation

### HACS (Recommended)

1. Go to HACS → Integrations
2. Click ⋮ → Custom repositories
3. Add URL: `https://github.com/remmob/timescale_database_reader`
4. Category: Integration
5. Search for 'Timescale Database Reader' and install
6. Restart Home Assistant

### Manual

1. Copy this repository to your Home Assistant `custom_components` directory:
   ```
   custom_components/timescale_database_reader
   ```
2. Restart Home Assistant.

## Configuration
In Home Assistant, go to **Settings > Integrations > Add Integration** and search for `Timescale Database Reader`. Enter your database host, port, username, password, and database name.

## Issues & Contributions
Problems or want to contribute? Open an issue or pull request on [GitHub](https://github.com/remmob/timescale_database_reader).

---
©2026 Bommer Software | Author: Mischa Bommer

> **Note:** This integration is a work in progress. Features and functionality may change or be incomplete.


