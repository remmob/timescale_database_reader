import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

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
            try:
                await self._async_test_connection(user_input)
                return self.async_create_entry(title="Timescale Database Reader", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, user_input=None):
        # Herconfiguratie (reauth) stap
        errors = {}
        if user_input is not None:
            try:
                await self._async_test_connection(user_input)
                entry_id = self.context.get("entry_id")
                entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
                if entry is not None:
                    self.hass.config_entries.async_update_entry(entry, data=user_input)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                return self.async_create_entry(title="Timescale Database Reader", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def _async_test_connection(self, data):
        def _test_connection():
            url = (
                f"postgresql+psycopg2://{data[CONF_USERNAME]}:{data[CONF_PASSWORD]}"
                f"@{data[CONF_HOST]}:{data[CONF_PORT]}/{data[CONF_DATABASE]}"
            )
            engine = create_engine(url, future=True)
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()

        try:
            await self.hass.async_add_executor_job(_test_connection)
        except SQLAlchemyError as exc:
            raise exc


async def async_get_options_flow(config_entry):
    return TimescaleDatabaseReaderOptionsFlowHandler(config_entry)


class TimescaleDatabaseReaderOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._async_test_connection(user_input)
                return self.async_create_entry(title="", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        data = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=data.get(CONF_PORT, 5432)): int,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_DATABASE, default=data.get(CONF_DATABASE, "")): str,
        })
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def _async_test_connection(self, data):
        def _test_connection():
            url = (
                f"postgresql+psycopg2://{data[CONF_USERNAME]}:{data[CONF_PASSWORD]}"
                f"@{data[CONF_HOST]}:{data[CONF_PORT]}/{data[CONF_DATABASE]}"
            )
            engine = create_engine(url, future=True)
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()

        try:
            await self.hass.async_add_executor_job(_test_connection)
        except SQLAlchemyError as exc:
            raise exc
