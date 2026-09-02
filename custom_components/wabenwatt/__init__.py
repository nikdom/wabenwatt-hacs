"""The Wabenwatt integration: reports a plant's live power to wabenwatt.de."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import (
    STATUS_OK,
    ReporterState,
    WabenwattCoordinator,
    pop_pending_report,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type WabenwattConfigEntry = ConfigEntry[WabenwattCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: WabenwattConfigEntry) -> bool:
    """Start reporting for one plant."""
    coordinator = WabenwattCoordinator(hass, entry)
    # The config/options flow just validated the token and sensors with a
    # real report of its own; reuse it instead of sending a second one
    # (coordinator.stash_first_report/pop_pending_report — avoids tripping
    # the server's 25s minimum report interval right after setup).
    pending = pop_pending_report(hass, entry.unique_id)
    if pending is not None:
        reading, at = pending
        coordinator.async_set_updated_data(
            ReporterState(status=STATUS_OK, last_report_at=at, last_reading=reading)
        )
    else:
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
