import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

DOMAIN = "timescale_database_reader"
CONF_DATABASE = "database"

DATA_SCHEMA = vol.Schema({
	vol.Required(CONF_HOST): str,
	vol.Required(CONF_PORT, default=5432): int,
	vol.Required(CONF_USERNAME): str,
	vol.Required(CONF_PASSWORD): str,
	vol.Required(CONF_DATABASE): str,
})

class TimescaleDatabaseReaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
	async def async_step_user(self, user_input=None):
		errors = {}
		if user_input is not None:
			return self.async_create_entry(title="Timescale Database Reader", data=user_input)
		return self.async_show_form(
			step_id="user",
			data_schema=DATA_SCHEMA,
			errors=errors,
		)

	async def async_step_reauth(self, user_input=None):
		# Herconfiguratie (reauth) stap
		errors = {}
		if user_input is not None:
			return self.async_create_entry(title="Timescale Database Reader", data=user_input)
		return self.async_show_form(
			step_id="reauth",
			data_schema=DATA_SCHEMA,
			errors=errors,
		)
