##
# Timescale Database Reader

A powerful Home Assistant integration for reading data from TimescaleDB databases.

## What does this integration do?
This integration allows you to easily read data from a Timescale (PostgreSQL) database and use it within Home Assistant. Perfect for accessing historical sensor data, energy usage, or any other time series stored in TimescaleDB.

### Key Features
- **Direct connection** to TimescaleDB/PostgreSQL
- **Configuration via the Home Assistant UI** (config flow)
- **Secure connection** with username and password
- **Support for custom queries**
- **Asynchronous data fetching** for optimal performance

## Installation
1. Copy this repository to your Home Assistant `custom_components` directory:
	```
	custom_components/timescale_database_reader/
	```
2. Restart Home Assistant.

## Configuration
In Home Assistant, go to **Settings > Integrations > Add Integration** and search for `Timescale Database Reader`. Enter your database host, port, username, password, and database name.

## Example Usage
After installation, you can use services or custom sensors to fetch data from your TimescaleDB. See the documentation for example queries.

## Issues & Contributions
Encounter a problem or want to contribute? Please open an issue or pull request on [GitHub](https://github.com/remmob/timescale_database_reader).

---
©2026 Bommer Software | Author: Mischa Bommer

> **Note:** This integration is a work in progress. Features and functionality may change or things might not work as expected.
