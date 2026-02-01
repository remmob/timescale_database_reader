# Timescale Database Reader

A powerful Home Assistant integration for reading data from any TimescaleDB database.

## Universal TimescaleDB Support
This integration works with any TimescaleDB (PostgreSQL) database, as long as you provide the correct connection details (host, port, username, password, database). You do not need a special Home Assistant database.

## Tested with LTSS and Scribe
This integration has been tested with a TimescaleDB database filled with values by the [LTSS integration](https://github.com/freol35241/ltss). Note: LTSS is no longer maintained. Currently, testing is ongoing with the [Home Assistant Scribe integration](https://github.com/jonathan-gatard/scribe) as an alternative for storing long-term statistics in TimescaleDB.

## Example Query
You can use the WebSocket API or a Home Assistant service to run a query. For example, to fetch the temperature of a sensor:

```
SELECT time, state
FROM ltss
WHERE entity_id = 'sensor.temperature_woonkamer'
  AND time BETWEEN '2026-01-01T00:00:00Z' AND '2026-01-01T12:00:00Z'
ORDER BY time ASC;
```

The integration also supports downsampling with `time_bucket` for efficient charting:

```
SELECT time_bucket('5 minutes', time) AS bucket,
       avg(state::double precision) AS avg_state
FROM ltss
WHERE entity_id = 'sensor.temperature_woonkamer'
  AND time BETWEEN '2026-01-01T00:00:00Z' AND '2026-01-01T12:00:00Z'
GROUP BY bucket
ORDER BY bucket ASC;
```

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

## Installation
1. Copy this repository to your Home Assistant `custom_components` directory:
   ```
   custom_components/timescale_database_reader/timescale_database_reader/
   ```
2. Restart Home Assistant.

## Configuration
In Home Assistant, go to **Settings > Integrations > Add Integration** and search for `Timescale Database Reader`. Enter your database host, port, username, password, and database name.

## Issues & Contributions
Problems or want to contribute? Open an issue or pull request on [GitHub](https://github.com/remmob/timescale_database_reader).

---
©2026 Bommer Software | Author: Mischa Bommer

> **Note:** This integration is a work in progress. Features and functionality may change or be incomplete.


