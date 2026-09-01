"""The Wabenwatt integration: reports a plant's live power to wabenwatt.de."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import WabenwattCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type WabenwattConfigEntry = ConfigEntry[WabenwattCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: WabenwattConfigEntry) -> bool:
    """Start reporting for one plant."""
    coordinator = WabenwattCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: WabenwattConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: WabenwattConfigEntry) -> bool:
    """Stop reporting for one plant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
