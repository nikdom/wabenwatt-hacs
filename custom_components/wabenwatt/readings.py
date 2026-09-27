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

from .const import NOT_CONFIGURED, PERCENT_UNITS, NotConfigured

# A sensor without unit is taken as watts (template sensors often have none);
# the API's plausibility check still catches a kW value sent as W.
_WATT_FACTORS: dict[str | None, float] = {
    None: 1,
    "mW": 0.001,
    "W": 1,
    "kW": 1_000,
    "MW": 1_000_000,
}

# Meter registers. No unitless default here: a counter without a unit is as
# likely kWh as Wh, and a factor of 1000 is not a guess worth making.
_WATT_HOUR_FACTORS: dict[str, float] = {
    "Wh": 1,
    "kWh": 1_000,
    "MWh": 1_000_000,
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


class SensorNotPercentError(Exception):
    """The entity is not a percentage sensor (state of charge)."""

    def __init__(self, entity_id: str, unit: str | None) -> None:
        super().__init__(f"{entity_id} is not a percentage sensor (unit {unit!r})")
        self.entity_id = entity_id
        self.unit = unit


class SensorNotEnergyError(Exception):
    """The entity is not an energy sensor (meter register in Wh/kWh/MWh)."""

    def __init__(self, entity_id: str, unit: str | None) -> None:
        super().__init__(f"{entity_id} is not an energy sensor (unit {unit!r})")
        self.entity_id = entity_id
        self.unit = unit


@dataclass(frozen=True)
class PlantReading:
    """What a PV plant reports: whole watts of solar power."""

    pv_power_w: int


@dataclass(frozen=True)
class BatteryReading:
    """What a battery device reports: whole watts, positive = discharging,
    plus the state of charge when a sensor for it is configured."""

    battery_power_w: int
    soc_percent: int | None


@dataclass(frozen=True)
class MeterReading:
    """What a grid meter reports: whole watts, positive = import from the grid,
    negative = export. Each register is whole watt-hours, None while its sensor
    has no value, NOT_CONFIGURED without a sensor."""

    grid_power_w: int
    import_energy_wh: int | None | NotConfigured = NOT_CONFIGURED
    export_energy_wh: int | None | NotConfigured = NOT_CONFIGURED


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


def read_percent(hass: HomeAssistant, entity_id: str) -> float:
    """Return a percentage sensor's current value, 0-100."""
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        raise SensorUnavailableError(entity_id)
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    # Unlike power, percent has no sensible unitless default: a state of charge
    # in kWh or W is a wrongly picked entity, not a unit to convert.
    if unit not in PERCENT_UNITS:
        raise SensorNotPercentError(entity_id, unit)
    try:
        value = float(state.state)
    except ValueError as err:
        raise SensorNotPercentError(entity_id, unit) from err
    if not math.isfinite(value):
        raise SensorUnavailableError(entity_id)
    # Clamp rather than reject: a battery reporting 100.4 % is a rounding
    # artefact of the BMS, not a broken configuration, and the API takes 0-100.
    return min(100.0, max(0.0, value))


def read_energy_wh(hass: HomeAssistant, entity_id: str) -> float:
    """Return an energy sensor's current value in watt-hours."""
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        raise SensorUnavailableError(entity_id)
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if unit not in _WATT_HOUR_FACTORS:
        raise SensorNotEnergyError(entity_id, unit)
    try:
        value = float(state.state)
    except ValueError as err:
        raise SensorNotEnergyError(entity_id, unit) from err
    # A negative register is a glitch, not a reading; the API requires >= 0.
    if not math.isfinite(value) or value < 0:
        raise SensorUnavailableError(entity_id)
    return value * _WATT_HOUR_FACTORS[unit]


def read_plant(hass: HomeAssistant, pv_sensors: list[str]) -> PlantReading:
    """Combine the configured sensors into one report.

    Every configured sensor has to deliver a value: summing only the strings
    that happen to be available would under-report silently, while sending
    nothing lets the plant turn inactive, which is the honest signal.
    """
    pv_total = sum(read_power_w(hass, entity_id) for entity_id in pv_sensors)
    # A few negative watts at night are the inverter's standby draw, which is
    # consumption, not production; the API requires powerW >= 0.
    return PlantReading(pv_power_w=max(0, round(pv_total)))


def read_battery(
    hass: HomeAssistant,
    battery_sensor: str,
    battery_invert: bool,
    soc_sensor: str | None,
) -> BatteryReading:
    """Read a battery device: power (and optionally its state of charge)."""
    power = read_power_w(hass, battery_sensor)
    if battery_invert:
        power = -power
    soc = None if soc_sensor is None else round(read_percent(hass, soc_sensor))
    return BatteryReading(battery_power_w=round(power), soc_percent=soc)


def read_meter(
    hass: HomeAssistant,
    *,
    grid_sensor: str | None,
    grid_invert: bool,
    import_sensor: str | None,
    export_sensor: str | None,
    import_energy_sensor: str | None,
    export_energy_sensor: str | None,
) -> MeterReading:
    """Read a grid meter: signed grid power plus the optional registers.

    Grid power comes EITHER from one signed sensor OR from import minus export.
    Unlike PV, a negative value is not clamped: here it is the export. Without
    grid power there is no report; a register without a value only becomes
    null, since the power value carries the report.
    """
    if grid_sensor is not None:
        power = read_power_w(hass, grid_sensor)
        if grid_invert:
            power = -power
    else:
        # The flow only stores this form with both sensors set.
        assert import_sensor is not None and export_sensor is not None
        power = read_power_w(hass, import_sensor) - read_power_w(hass, export_sensor)
    return MeterReading(
        grid_power_w=round(power),
        import_energy_wh=_optional_energy_wh(hass, import_energy_sensor),
        export_energy_wh=_optional_energy_wh(hass, export_energy_sensor),
    )


def _optional_energy_wh(
    hass: HomeAssistant, entity_id: str | None
) -> int | None | NotConfigured:
    if entity_id is None:
        return NOT_CONFIGURED
    try:
        return round(read_energy_wh(hass, entity_id))
    except SensorUnavailableError:
        return None
