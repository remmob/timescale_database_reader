from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN].get("_coordinators", {}).get(entry.entry_id)
    meta = hass.data[DOMAIN].get("_entry_meta", {}).get(entry.entry_id, {})
    if coordinator is None:
        return
    async_add_entities([TimescaleConnectionStatus(coordinator, entry.entry_id, meta)])


class TimescaleConnectionStatus(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, meta: dict):
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._meta = meta
        db_name = meta.get("database") or "database"
        self._attr_name = f"TimescaleDB Connection ({db_name})"
        self._attr_unique_id = f"{entry_id}_connection"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": f"TimescaleDB ({db_name})",
            "manufacturer": "TimescaleDB",
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return bool(data.get("connected"))

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        attrs = {
            "database": self._meta.get("database"),
            "table": self._meta.get("table"),
        }
        if data.get("error"):
            attrs["error"] = data.get("error")
        return attrs
