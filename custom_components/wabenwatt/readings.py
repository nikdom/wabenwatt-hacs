"""Reading power values from Home Assistant sensor states."""

from __future__ import annotations

from dataclasses import dataclass
import math

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

# A sensor without unit is taken as watts (template sensors often have none);
# the API's plausibility check still catches a kW value sent as W.
_WATT_FACTORS: dict[str | None, float] = {
    None: 1,
    "mW": 0.001,
    "W": 1,
    "kW": 1_000,
    "MW": 1_000_000,
}


class SensorUnavailableError(Exception):
    """The sensor exists but has no numeric value right now."""

    def __init__(self, entity_id: str) -> None:
        super().__init__(f"{entity_id} has no numeric state")
        self.entity_id = entity_id


class SensorNotPowerError(Exception):
    """The entity is not a power sensor (wrong unit or non-numeric state)."""

    def __init__(self, entity_id: str, unit: str | None) -> None:
        super().__init__(f"{entity_id} is not a power sensor (unit {unit!r})")
        self.entity_id = entity_id
        self.unit = unit


@dataclass(frozen=True)
class PlantReading:
    """What gets reported: whole watts, battery positive = discharging."""

    pv_power_w: int
    battery_power_w: int | None


def read_power_w(hass: HomeAssistant, entity_id: str) -> float:
    """Return the sensor's current value in watts."""
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        raise SensorUnavailableError(entity_id)
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if unit not in _WATT_FACTORS:
        raise SensorNotPowerError(entity_id, unit)
    try:
        value = float(state.state)
    except ValueError as err:
        raise SensorNotPowerError(entity_id, unit) from err
    if not math.isfinite(value):
        raise SensorUnavailableError(entity_id)
    return value * _WATT_FACTORS[unit]


def read_plant(
    hass: HomeAssistant,
    pv_sensors: list[str],
    battery_sensor: str | None,
    battery_invert: bool,
) -> PlantReading:
    """Combine the configured sensors into one report.

    Every configured sensor has to deliver a value: summing only the strings
    that happen to be available would under-report silently, while sending
    nothing lets the plant turn inactive, which is the honest signal.
    """
    pv_total = sum(read_power_w(hass, entity_id) for entity_id in pv_sensors)
    battery: float | None = None
    if battery_sensor:
        battery = read_power_w(hass, battery_sensor)
        if battery_invert:
            battery = -battery
    # A few negative watts at night are the inverter's standby draw, which is
    # consumption, not production; the API requires powerW >= 0.
    return PlantReading(
        pv_power_w=max(0, round(pv_total)),
        battery_power_w=None if battery is None else round(battery),
    )
