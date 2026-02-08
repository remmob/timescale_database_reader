import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from .const import DOMAIN, CONF_TABLE, CONF_NAME

CONF_DATABASE = "database"

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME, default="Timescale DB"): str,
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=5432): int,
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required(CONF_DATABASE): str,
    vol.Required(CONF_TABLE, default="ltss"): str,
})

class TimescaleDatabaseReaderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    @staticmethod
    def async_get_options_flow(config_entry):
        return TimescaleDatabaseReaderOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._async_test_connection(user_input)
                title = user_input.get(CONF_NAME, "Timescale DB")
                return self.async_create_entry(title=title, data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))

        if user_input is not None:
            try:
                await self._async_test_connection(user_input)
                if entry is not None:
                    new_title = user_input.get(CONF_NAME, entry.title)
                    self.hass.config_entries.async_update_entry(
                        entry,
                        title=new_title,
                        data={**entry.data, **user_input},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
                title = user_input.get(CONF_NAME, "Timescale DB")
                return self.async_create_entry(title=title, data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        data = {**(entry.data if entry else {}), **(entry.options if entry else {})}
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=data.get(CONF_NAME, entry.title if entry else "Timescale DB")): str,
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=data.get(CONF_PORT, 5432)): int,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_DATABASE, default=data.get(CONF_DATABASE, "")): str,
            vol.Required(CONF_TABLE, default=data.get(CONF_TABLE, "ltss")): str,
        })
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
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
                    new_title = user_input.get(CONF_NAME, entry.title)
                    self.hass.config_entries.async_update_entry(entry, title=new_title, data=user_input)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                title = user_input.get(CONF_NAME, "Timescale DB")
                return self.async_create_entry(title=title, data=user_input)
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


class TimescaleDatabaseReaderOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._async_test_connection(user_input)
                new_title = user_input.get(CONF_NAME, self._config_entry.title)
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    title=new_title,
                )
                return self.async_create_entry(title="", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"

        data = {**self._config_entry.data, **self._config_entry.options}
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=data.get(CONF_NAME, self._config_entry.title)): str,
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=data.get(CONF_PORT, 5432)): int,
            vol.Required(CONF_USERNAME, default=data.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=data.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_DATABASE, default=data.get(CONF_DATABASE, "")): str,
            vol.Required(CONF_TABLE, default=data.get(CONF_TABLE, "ltss")): str,
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
