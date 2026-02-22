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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import DOMAIN, CONF_TABLE, CONF_NAME
from .db import TimescaleDBConnection
from homeassistant.components import websocket_api
from datetime import datetime
import voluptuous as vol
import logging
import re
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor"]

_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str, name: str) -> str:
    if not value or not _VALID_IDENTIFIER.match(value):
        raise ValueError(f"Invalid {name}: {value}")
    return value


def _safe_table_ref(value: str) -> str:
    if not value:
        raise ValueError("Invalid table: empty")
    parts = value.split(".")
    if len(parts) > 2:
        raise ValueError(f"Invalid table: {value}")
    safe_parts = [_safe_identifier(p, "table") for p in parts]
    return ".".join(safe_parts)


def _split_table_ref(table_ref: str) -> tuple[str, str]:
    parts = table_ref.split(".")
    if len(parts) == 2:
        return parts[0], parts[1]
    return "public", parts[0]


async def _fetch_table_columns(db: TimescaleDBConnection, table_ref: str) -> set[str]:
    schema, table = _split_table_ref(table_ref)
    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name = :table
    """
    try:
        rows = await db.fetch(query, schema=schema, table=table)
        return {row.get("column_name") for row in rows if row.get("column_name")}
    except Exception as exc:
        _LOGGER.warning("Failed to fetch columns for %s: %s", table_ref, exc)
        return set()

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
    hass.data.setdefault(DOMAIN, {})
    if "_service_registered" not in hass.data[DOMAIN]:
        async def _handle_reconfigure(call):
            entry_id = call.data.get("entry_id")
            database = call.data.get("database")

            entry_ids = []
            if entry_id:
                entry_ids = [entry_id]
            elif database:
                metas = hass.data.get(DOMAIN, {}).get("_entry_meta", {})
                entry_ids = [eid for eid, meta in metas.items() if meta.get("database") == database]
            else:
                entry_ids = [
                    eid for eid in hass.data.get(DOMAIN, {})
                    if not str(eid).startswith("_")
                ]

            if not entry_ids:
                _LOGGER.warning("Reconfigure requested but no matching entries found")
                return

            for eid in entry_ids:
                await hass.config_entries.async_reload(eid)

        hass.services.async_register(
            DOMAIN,
            "reconfigure",
            _handle_reconfigure,
            schema=vol.Schema({
                vol.Optional("entry_id"): str,
                vol.Optional("database"): str,
            }),
        )
        hass.data[DOMAIN]["_service_registered"] = True
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
    db_conf = {**entry.data, **entry.options}
    db = TimescaleDBConnection(
        host=db_conf["host"],
        port=db_conf["port"],
        user=db_conf["username"],
        password=db_conf["password"],
        database=db_conf["database"]
    )
    await db.connect()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = db
    hass.data[DOMAIN].setdefault("_entry_meta", {})[entry.entry_id] = {
        "database": db_conf.get("database"),
        "table": db_conf.get(CONF_TABLE, "ltss"),
        "name": db_conf.get(CONF_NAME, entry.title),
    }
    try:
        table_ref = _safe_table_ref(db_conf.get(CONF_TABLE, "ltss"))
        columns = await _fetch_table_columns(db, table_ref)
        hass.data[DOMAIN]["_entry_meta"][entry.entry_id]["columns"] = columns
    except Exception as exc:
        _LOGGER.warning("Failed to initialize table metadata for %s: %s", entry.entry_id, exc)
    hass.data[DOMAIN].setdefault("_coordinators", {})

    async def _async_update_connection():
        try:
            await db.fetch("SELECT 1")
            return {"connected": True, "error": None}
        except Exception as exc:
            _LOGGER.warning("Connection check failed for %s: %s", entry.entry_id, exc)
            return {"connected": False, "error": str(exc)}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{entry.entry_id}",
        update_method=_async_update_connection,
        update_interval=timedelta(seconds=30),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN]["_coordinators"][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register WebSocket API handler (only once per HA instance, not per config entry)
    if '_websocket_registered' not in hass.data[DOMAIN]:

        def _resolve_db_entry(msg):
            entry_id = msg.get("entry_id")
            if entry_id:
                db = hass.data.get(DOMAIN, {}).get(entry_id)
                meta = hass.data.get(DOMAIN, {}).get("_entry_meta", {}).get(entry_id)
                return entry_id, db, meta

            database = msg.get("database")
            if database:
                database_key = str(database).casefold()
                metas = hass.data.get(DOMAIN, {}).get("_entry_meta", {})
                for eid, meta in metas.items():
                    meta_db = str(meta.get("database", "")).casefold()
                    meta_name = str(meta.get("name", "")).casefold()
                    if meta_db == database_key or meta_name == database_key:
                        db = hass.data.get(DOMAIN, {}).get(eid)
                        return eid, db, meta

            entries = hass.data.get(DOMAIN, {})
            if entries:
                entry_ids = [eid for eid in entries.keys() if not str(eid).startswith("_")]
                if entry_ids:
                    entry_id = entry_ids[0]
                    db = entries.get(entry_id)
                    meta = hass.data.get(DOMAIN, {}).get("_entry_meta", {}).get(entry_id)
                    return entry_id, db, meta

            return None, None, None
        
        @websocket_api.websocket_command({
            vol.Required("type"): "timescale/query",
            vol.Required("sensor_id"): str,
            vol.Required("start"): vol.Any(str, int, float),
            vol.Required("end"): vol.Any(str, int, float),
            vol.Optional("limit", default=0): int,
            vol.Optional("entry_id"): str,
            vol.Optional("database"): str,
            vol.Optional("downsample", default=0): int,
            vol.Optional("table"): str,
            vol.Optional("downsample_method"): vol.In(["avg", "last"]),
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

                entry_id, db, meta = _resolve_db_entry(msg)
                if db is None:
                    raise ValueError("No database connection available")

                if meta is None:
                    raise ValueError("No database metadata available")

                requested_table = msg.get("table")
                if requested_table:
                    table_ref = _safe_table_ref(requested_table)
                else:
                    table_ref = _safe_table_ref(meta.get("table", "ltss"))

                default_table_ref = _safe_table_ref(meta.get("table", "ltss"))
                if table_ref == default_table_ref:
                    columns = meta.get("columns") or set()
                else:
                    cache = hass.data[DOMAIN].setdefault("_table_columns_cache", {})
                    entry_cache = cache.setdefault(entry_id, {})
                    columns = entry_cache.get(table_ref)
                    if not columns:
                        columns = await _fetch_table_columns(db, table_ref)
                        entry_cache[table_ref] = columns

                if "time" in columns:
                    time_col = "time"
                elif "bucket" in columns:
                    time_col = "bucket"
                elif "minute" in columns:
                    time_col = "minute"
                else:
                    raise ValueError(f"Table {table_ref} has no supported time column (expected time, bucket or minute)")

                has_value = "value" in columns

                downsample = int(msg.get("downsample", 0))
                downsample_method = str(msg.get("downsample_method") or "").lower()
                if downsample_method not in {"avg", "last"}:
                    if requested_table and time_col in {"bucket", "minute"}:
                        downsample_method = "last"
                    else:
                        downsample_method = "avg"
                _LOGGER.info(f"[WEBSOCKET] Query params: sensor_id={sensor_id}, start={start}, end={end}, downsample={downsample}, limit={limit}")
                
                if downsample and downsample > 0:
                    if has_value:
                        value_expr = "COALESCE(value, CASE WHEN state ~ '^-?\\d+(\\.\\d+)?$' THEN state::double precision END)"
                        numeric_filter = "(value IS NOT NULL OR state ~ '^-?\\d+(\\.\\d+)?$')"
                    else:
                        value_expr = "CASE WHEN state ~ '^-?\\d+(\\.\\d+)?$' THEN state::double precision END"
                        numeric_filter = "state ~ '^-?\\d+(\\.\\d+)?$'"
                    if downsample_method == "last":
                        downsample_expr = f"last({value_expr}, {time_col})"
                    else:
                        downsample_expr = f"avg({value_expr})"
                    bucket_query = fr"""
                        SELECT
                            time_bucket(:bucket, {time_col}) AS bucket,
                            {downsample_expr} AS avg_state,
                            min({value_expr}) AS min_state,
                            max({value_expr}) AS max_state
                        FROM {table_ref}
                        WHERE entity_id = :entity_id
                          AND {time_col} BETWEEN :start AND :end
                          AND {numeric_filter}
                        GROUP BY bucket
                        ORDER BY bucket ASC
                    """
                    rows = await db.fetch(bucket_query, entity_id=sensor_id, start=start, end=end, bucket=f"{downsample} seconds")
                    _LOGGER.info(f"[WEBSOCKET] Downsampled query returned {len(rows) if isinstance(rows, list) else 'N/A'} rows")
                    if isinstance(rows, list) and len(rows) > MAX_RETURN_ROWS:
                        raise ValueError(f"Result too large: {len(rows)} rows exceeds max {MAX_RETURN_ROWS}")
                    connection.send_message(websocket_api.result_message(msg["id"], rows))
                else:
                    if has_value:
                        value_expr = "COALESCE(value, CASE WHEN state ~ '^-?\\d+(\\.\\d+)?$' THEN state::double precision END)"
                        numeric_filter = "(value IS NOT NULL OR state ~ '^-?\\d+(\\.\\d+)?$')"
                    else:
                        value_expr = "CASE WHEN state ~ '^-?\\d+(\\.\\d+)?$' THEN state::double precision END"
                        numeric_filter = "state ~ '^-?\\d+(\\.\\d+)?$'"
                    query = fr"""
                                                SELECT {time_col} AS time, {value_expr} AS state
                        FROM {table_ref}
                        WHERE entity_id = :entity_id
                                                    AND {time_col} BETWEEN :start AND :end
                          AND {numeric_filter}
                                                ORDER BY {time_col} ASC
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
    end = datetime.utcnow()
    start = end - timedelta(hours=1)
    meta = hass.data[DOMAIN].get("_entry_meta", {}).get(entry.entry_id, {})
    table_ref = _safe_table_ref(meta.get("table", "ltss"))
    query = f"""
        SELECT time, state
        FROM {table_ref}
        WHERE entity_id = :entity_id AND time BETWEEN :start AND :end
        ORDER BY time ASC
    """
    try:
        rows = await db.fetch(query, entity_id=entity_id, start=start, end=end)
        _LOGGER.info(f"Timescale test query: {len(rows)} rows retrieved for {entity_id} between {start} and {end}")
    except Exception as e:
        _LOGGER.warning(f"Error executing test query: {e}")

    # WebSocket API only - no platform setup needed
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Close database connection
    db = hass.data[DOMAIN].pop(entry.entry_id, None)
    if db:
        await db.close()
    meta = hass.data.get(DOMAIN, {}).get("_entry_meta", {})
    if isinstance(meta, dict):
        meta.pop(entry.entry_id, None)
    coordinators = hass.data.get(DOMAIN, {}).get("_coordinators", {})
    if isinstance(coordinators, dict):
        coordinators.pop(entry.entry_id, None)
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
