"""Entities showing what was reported and whether reporting works."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WabenwattConfigEntry
from .const import APP_URL, CONF_PLANT_ID, CONF_SOURCE_TYPE, DOMAIN, PLANT_PAGE_URL
from .coordinator import STATUSES, ReporterState, WabenwattCoordinator


@dataclass(frozen=True, kw_only=True)
class WabenwattSensorDescription(SensorEntityDescription):
    """Describes one entity derived from the reporter state."""

    value_fn: Callable[[ReporterState], StateType | datetime]
    attributes_fn: Callable[[ReporterState], dict[str, Any]] | None = None
    requires_battery: bool = False


def _error_attributes(state: ReporterState) -> dict[str, Any]:
    if state.last_error is None:
        return {}
    return {
        "message": state.last_error.message,
        "at": state.last_error.at.isoformat(),
    }


SENSORS: tuple[WabenwattSensorDescription, ...] = (
    WabenwattSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.status,
        attributes_fn=lambda state: {"blocking_entity": state.blocking_entity},
    ),
    WabenwattSensorDescription(
        key="last_report",
        translation_key="last_report",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.last_report_at,
    ),
    WabenwattSensorDescription(
        key="last_error",
        translation_key="last_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.last_error.code if state.last_error else None,
        attributes_fn=_error_attributes,
    ),
    WabenwattSensorDescription(
        key="reported_power",
        translation_key="reported_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: (
            state.last_reading.pv_power_w if state.last_reading else None
        ),
    ),
    WabenwattSensorDescription(
        key="reported_battery_power",
        translation_key="reported_battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        requires_battery=True,
        value_fn=lambda state: (
            state.last_reading.battery_power_w if state.last_reading else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WabenwattConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the entities for one plant."""
    coordinator = entry.runtime_data
    async_add_entities(
        WabenwattSensor(coordinator, description)
        for description in SENSORS
        if not description.requires_battery or coordinator.battery_sensor
    )


class WabenwattSensor(CoordinatorEntity[WabenwattCoordinator], SensorEntity):
    """One value of the reporter state."""

    entity_description: WabenwattSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WabenwattCoordinator,
        description: WabenwattSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        plant_id = entry.data.get(CONF_PLANT_ID)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wabenwatt",
            model=entry.data.get(CONF_SOURCE_TYPE, "pv").upper(),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                PLANT_PAGE_URL.format(plant_id=plant_id) if plant_id else APP_URL
            ),
        )

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
