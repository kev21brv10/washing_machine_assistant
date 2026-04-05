from __future__ import annotations

from typing import TYPE_CHECKING

from .const import DOMAIN, PLATFORMS, SERVICE_RENAME_LEARNED_MODE

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall
    from homeassistant.helpers import entity_registry as er


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import WashingMachineCoordinator
    import voluptuous as vol

    coordinator = WashingMachineCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_RENAME_LEARNED_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RENAME_LEARNED_MODE,
            _handle_rename_learned_mode,
            schema=vol.Schema(
                {
                    vol.Required("mode_slug"): vol.Coerce(str),
                    vol.Required("new_name"): vol.All(vol.Coerce(str), vol.Length(min=1, max=80)),
                    vol.Optional("entity_id"): vol.Coerce(str),
                }
            ),
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _handle_rename_learned_mode(call: ServiceCall) -> None:
    from .coordinator import WashingMachineCoordinator
    from homeassistant.exceptions import HomeAssistantError

    hass = call.hass
    coordinator = _resolve_coordinator(hass, call.data.get("entity_id"))
    renamed = await coordinator.async_rename_learned_profile(
        mode_slug=call.data["mode_slug"],
        new_name=call.data["new_name"],
    )
    if not renamed:
        raise HomeAssistantError(f"Learned mode not found: {call.data['mode_slug']}")


def _resolve_coordinator(hass: HomeAssistant, entity_id: str | None) -> "WashingMachineCoordinator":
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import entity_registry as er

    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError("No washing machine assistant entry is loaded")

    if entity_id is None:
        if len(coordinators) == 1:
            return coordinators[0]
        raise HomeAssistantError("entity_id is required when multiple washing machine entries exist")

    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)
    if entity_entry is None:
        raise HomeAssistantError(f"Unknown entity_id: {entity_id}")

    coordinator = hass.data.get(DOMAIN, {}).get(entity_entry.config_entry_id)
    if coordinator is None:
        raise HomeAssistantError(f"No coordinator found for entity_id: {entity_id}")
    return coordinator
