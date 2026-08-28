DOMAIN = "timescale_database_reader"

# Config keys
CONF_NAME = "name"
CONF_TABLE = "table"

# When enabled, a query returns every remaining column of the queried table on
# top of the fixed set (bucket/time, state, avg_state, min_state, max_state).
# Off by default, so existing setups keep the exact same result shape.
CONF_INCLUDE_EXTRA_COLUMNS = "include_extra_columns"

# Device info
DEVICE_INFO = {
    "copyright": "©2026 Bommer Software",
    "author": "Mischa Bommer"
}
