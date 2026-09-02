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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WabenwattConfigEntry
from .const import (
    APP_URL,
    BATTERY_PAGE_URL,
    CONF_BATTERY_ID,
    CONF_PLANT_ID,
    CONF_SOURCE_TYPE,
    DOMAIN,
    PLANT_PAGE_URL,
    SOURCE_TYPE_BATTERY,
    SOURCE_TYPE_PV,
)
from .coordinator import STATUSES, ReporterState, WabenwattCoordinator
from .readings import BatteryReading, PlantReading


@dataclass(frozen=True, kw_only=True)
class WabenwattSensorDescription(SensorEntityDescription):
    """Describes one entity derived from the reporter state."""

    value_fn: Callable[[ReporterState], StateType | datetime]
    attributes_fn: Callable[[ReporterState], dict[str, Any]] | None = None
    # Which device types show this entity; None = all of them.
    source_types: tuple[str, ...] | None = None


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
        source_types=(SOURCE_TYPE_PV,),
        value_fn=lambda state: (
            state.last_reading.pv_power_w
            if isinstance(state.last_reading, PlantReading)
            else None
        ),
    ),
    WabenwattSensorDescription(
        key="reported_battery_power",
        translation_key="reported_battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        source_types=(SOURCE_TYPE_BATTERY,),
        value_fn=lambda state: (
            state.last_reading.battery_power_w
            if isinstance(state.last_reading, BatteryReading)
            else None
        ),
    ),
    WabenwattSensorDescription(
        key="reported_soc",
        translation_key="reported_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        source_types=(SOURCE_TYPE_BATTERY,),
        value_fn=lambda state: (
            state.last_reading.soc_percent
            if isinstance(state.last_reading, BatteryReading)
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WabenwattConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the entities for one device."""
    coordinator = entry.runtime_data
    async_add_entities(
        WabenwattSensor(coordinator, description)
        for description in SENSORS
        if _applies(description, coordinator)
    )


def _applies(
    description: WabenwattSensorDescription, coordinator: WabenwattCoordinator
) -> bool:
    """Whether this entity exists for the entry's device type and options."""
    if (
        description.source_types is not None
        and coordinator.source_type not in description.source_types
    ):
        return False
    # State of charge is optional even on a battery; without a sensor the
    # entity would sit at "unknown" forever.
    return description.key != "reported_soc" or coordinator.soc_sensor is not None


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
        source_type = entry.data.get(CONF_SOURCE_TYPE, SOURCE_TYPE_PV)
        device_id = entry.data.get(
            CONF_BATTERY_ID if source_type == SOURCE_TYPE_BATTERY else CONF_PLANT_ID
        )
        page = (
            BATTERY_PAGE_URL if source_type == SOURCE_TYPE_BATTERY else PLANT_PAGE_URL
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wabenwatt",
            model=source_type.upper(),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=(
                page.format(plant_id=device_id, battery_id=device_id)
                if device_id
                else APP_URL
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
