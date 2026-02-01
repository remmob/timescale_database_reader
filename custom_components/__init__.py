
"""
TimescaleDB Database Reader Integration for Home Assistant

This integration provides a WebSocket API to query historical sensor data
from a TimescaleDB database. It supports:
- Time-based queries with start/end timestamps
- Automatic downsampling using TimescaleDB's time_bucket function
- Data limits and validation
- Multiple database connections via config entries

Author: Your Name
Version: 1.0.0
License: MIT
"""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .db import TimescaleDBConnection
from homeassistant.components import websocket_api
from datetime import datetime
import voluptuous as vol
import logging

_LOGGER = logging.getLogger(__name__)

# No platforms needed - using WebSocket API only


async def async_setup(hass, config):
	"""
	Set up the Timescale Database Reader component (YAML, legacy).
    
	Args:
		hass: Home Assistant instance
		config: YAML configuration
        
	Returns:
		bool: Always True (setup handled by config_flow)
	"""
	return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
	"""
	Set up Timescale Database Reader from a config entry.
    
	Initializes database connection and registers WebSocket API handler.
    
	Args:
		hass: Home Assistant instance
		entry: Config entry with database credentials
        
	Returns:
		bool: True if setup successful
	"""
	# Create database connection from config entry
	db_conf = entry.data
	db = TimescaleDBConnection(
		host=db_conf["host"],
		port=db_conf["port"],
		user=db_conf["username"],
		password=db_conf["password"],
		database=db_conf["database"]
	)
	await db.connect()
	hass.data.setdefault(DOMAIN, {})[entry.entry_id] = db

	# Register WebSocket API handler (only once per HA instance, not per config entry)
	if '_websocket_registered' not in hass.data[DOMAIN]:
        
		@websocket_api.websocket_command({
			vol.Required("type"): "timescale/query",
			vol.Required("sensor_id"): str,
			vol.Required("start"): vol.Any(str, int, float),
			vol.Required("end"): vol.Any(str, int, float),
			vol.Optional("limit", default=0): int,
			vol.Optional("entry_id"): str,
			vol.Optional("downsample", default=0): int,
		})
		@websocket_api.async_response
		async def handle_timescale_query(hass, connection, msg):
			"""
			Handle WebSocket query messages from frontend.
            
			Queries TimescaleDB for historical sensor data with optional downsampling.
            
			Args:
				hass: Home Assistant instance
				connection: WebSocket connection
				msg: Message with query parameters:
					- sensor_id: Entity ID to query
					- start: Start timestamp (ISO string or Unix timestamp)
					- end: End timestamp (ISO string or Unix timestamp)
					- limit: Maximum rows to return (0 = no limit)
					- downsample: Bucket size in seconds (0 = raw data)
					- entry_id: Optional specific database connection
                    
			Returns:
				JSON array of data points via WebSocket
			"""
			try:
				_LOGGER.warning(f"[WEBSOCKET] Received query: {msg}")
				sensor_id = msg["sensor_id"]
				start_raw = msg["start"]
				end_raw = msg["end"]
				limit = int(msg["limit"])

				def _parse_time(v):
					"""
					Parse timestamp from various formats.
                    
					Supports:
					- Unix timestamp (int/float)
					- ISO 8601 string (with or without Z suffix)
                    
					Args:
						v: Timestamp value
                        
					Returns:
						datetime: Parsed datetime object
                        
					Raises:
						ValueError: If format is invalid
					"""
					if isinstance(v, (int, float)):
						return datetime.utcfromtimestamp(float(v))
					if isinstance(v, str):
						try:
							if v.endswith("Z"):
								v = v[:-1] + "+00:00"
							return datetime.fromisoformat(v)
						except Exception:
							raise
					raise ValueError("invalid time format")

				try:
					start = _parse_time(start_raw)
					end = _parse_time(end_raw)
				except Exception as e:
					_LOGGER.error(f"[WEBSOCKET] Time parse error: {e}")
					raise ValueError(f"Invalid time format: {e}")

				MAX_DURATION_SECONDS = 365 * 24 * 3600  # 7 days
				MAX_LIMIT = 10000
				MAX_RETURN_ROWS = 50000

				duration = (end - start).total_seconds()
				if duration <= 0:
					raise ValueError("Invalid time range: end must be after start")
				if duration > MAX_DURATION_SECONDS:
					raise ValueError(f"Time range too large: max {MAX_DURATION_SECONDS}s")
				if limit < 0 or limit > MAX_LIMIT:
					raise ValueError(f"Invalid limit: must be 0-{MAX_LIMIT}")

				entry_id = msg.get("entry_id")
				if entry_id:
					db = hass.data.get(DOMAIN, {}).get(entry_id)
				else:
					entries = hass.data.get(DOMAIN, {})
					if entries:
						entry_id = list(entries.keys())[0]
						db = entries[entry_id]
						_LOGGER.debug(f"Using default entry_id: {entry_id}")
					else:
						db = None

				if db is None:
					raise ValueError("No database connection available")

				downsample = int(msg.get("downsample", 0))
				_LOGGER.info(f"[WEBSOCKET] Query params: sensor_id={sensor_id}, start={start}, end={end}, downsample={downsample}, limit={limit}")
                
				if downsample and downsample > 0:
					bucket_query = """
						SELECT
							time_bucket(:bucket, time) AS bucket,
							avg(CASE WHEN state ~ '^-?\d+(\.\d+)?$' THEN state::double precision END) AS avg_state,
							min(CASE WHEN state ~ '^-?\d+(\.\d+)?$' THEN state::double precision END) AS min_state,
							max(CASE WHEN state ~ '^-?\d+(\.\d+)?$' THEN state::double precision END) AS max_state
						FROM ltss
						WHERE entity_id = :entity_id
						  AND time BETWEEN :start AND :end
						GROUP BY bucket
						ORDER BY bucket ASC
					"""
					rows = await db.fetch(bucket_query, entity_id=sensor_id, start=start, end=end, bucket=f"{downsample} seconds")
					_LOGGER.info(f"[WEBSOCKET] Downsampled query returned {len(rows) if isinstance(rows, list) else 'N/A'} rows")
					if isinstance(rows, list) and len(rows) > MAX_RETURN_ROWS:
						raise ValueError(f"Result too large: {len(rows)} rows exceeds max {MAX_RETURN_ROWS}")
					connection.send_message(websocket_api.result_message(msg["id"], rows))
				else:
					query = """
						SELECT time, state
						FROM ltss
						WHERE entity_id = :entity_id
						  AND time BETWEEN :start AND :end
						  AND state ~ '^-?\d+(\.\d+)?$'
						ORDER BY time ASC
					"""
					rows = await db.fetch(query, entity_id=sensor_id, start=start, end=end)
					_LOGGER.info(f"[WEBSOCKET] Raw query returned {len(rows) if isinstance(rows, list) else 'N/A'} rows")
					if isinstance(rows, list):
						if limit:
							rows = rows[-int(limit):]
						if len(rows) > MAX_RETURN_ROWS:
							raise ValueError(f"Result too large: {len(rows)} rows exceeds max {MAX_RETURN_ROWS}")
					connection.send_message(websocket_api.result_message(msg["id"], rows))
                    
				_LOGGER.warning(f"[WEBSOCKET] Successfully sent response")
			except Exception as e:
				_LOGGER.error(f"[WEBSOCKET] FATAL ERROR: {e}", exc_info=True)
				connection.send_message(websocket_api.error_message(msg["id"], "query_failed", str(e)))
        
		websocket_api.async_register_command(hass, handle_timescale_query)
		hass.data[DOMAIN]['_websocket_registered'] = True

	# Execute example query and log results for testing
	entity_id = "sensor.temperature_woonkamer"  # Change to an existing entity_id
	from datetime import datetime, timedelta
	end = datetime.utcnow()
	start = end - timedelta(hours=1)
	query = """
		SELECT time, state
		FROM ltss
		WHERE entity_id = :entity_id AND time BETWEEN :start AND :end
		ORDER BY time ASC
	"""
	try:
		rows = await db.fetch(query, entity_id=entity_id, start=start, end=end)
		_LOGGER.info(f"Timescale test query: {len(rows)} rows retrieved for {entity_id} between {start} and {end}")
	except Exception as e:
		_LOGGER.error(f"Error executing test query: {e}")

	# WebSocket API only - no platform setup needed
	return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
	"""Unload a config entry."""
	# Close database connection
	db = hass.data[DOMAIN].pop(entry.entry_id, None)
	if db:
		await db.close()
	return True
