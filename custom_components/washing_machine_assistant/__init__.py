from __future__ import annotations

from typing import TYPE_CHECKING

from .const import (
    DOMAIN,
    PLATFORMS,
    SERVICE_CONFIRM_LEARNED_MODE,
    SERVICE_DELETE_LEARNED_MODE,
    SERVICE_MERGE_LEARNED_MODES,
    SERVICE_RENAME_LEARNED_MODE,
)

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
    if not hass.services.has_service(DOMAIN, SERVICE_DELETE_LEARNED_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_LEARNED_MODE,
            _handle_delete_learned_mode,
            schema=vol.Schema(
                {
                    vol.Required("mode_slug"): vol.Coerce(str),
                    vol.Optional("entity_id"): vol.Coerce(str),
                }
            ),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_MERGE_LEARNED_MODES):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MERGE_LEARNED_MODES,
            _handle_merge_learned_modes,
            schema=vol.Schema(
                {
                    vol.Required("source_mode_slug"): vol.Coerce(str),
                    vol.Required("target_mode_slug"): vol.Coerce(str),
                    vol.Optional("entity_id"): vol.Coerce(str),
                }
            ),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CONFIRM_LEARNED_MODE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CONFIRM_LEARNED_MODE,
            _handle_confirm_learned_mode,
            schema=vol.Schema(
                {
                    vol.Required("mode_slug"): vol.Coerce(str),
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
    from homeassistant.exceptions import HomeAssistantError

    hass = call.hass
    coordinator = _resolve_coordinator(hass, call.data.get("entity_id"))
    renamed = await coordinator.async_rename_learned_profile(
        mode_slug=call.data["mode_slug"],
        new_name=call.data["new_name"],
    )
    if not renamed:
        raise HomeAssistantError(f"Mode appris introuvable : {call.data['mode_slug']}")


async def _handle_delete_learned_mode(call: ServiceCall) -> None:
    from homeassistant.exceptions import HomeAssistantError

    coordinator = _resolve_coordinator(call.hass, call.data.get("entity_id"))
    deleted = await coordinator.async_delete_learned_profile(mode_slug=call.data["mode_slug"])
    if not deleted:
        raise HomeAssistantError(f"Mode appris introuvable : {call.data['mode_slug']}")


async def _handle_merge_learned_modes(call: ServiceCall) -> None:
    from homeassistant.exceptions import HomeAssistantError

    coordinator = _resolve_coordinator(call.hass, call.data.get("entity_id"))
    merged = await coordinator.async_merge_learned_profiles(
        source_slug=call.data["source_mode_slug"],
        target_slug=call.data["target_mode_slug"],
    )
    if not merged:
        raise HomeAssistantError("Fusion impossible pour les modes appris demandes")


async def _handle_confirm_learned_mode(call: ServiceCall) -> None:
    from homeassistant.exceptions import HomeAssistantError

    coordinator = _resolve_coordinator(call.hass, call.data.get("entity_id"))
    confirmed = await coordinator.async_confirm_learned_profile(mode_slug=call.data["mode_slug"])
    if not confirmed:
        raise HomeAssistantError(
            "Confirmation impossible : cycle termine introuvable ou mode appris inexistant"
        )


def _resolve_coordinator(hass: HomeAssistant, entity_id: str | None) -> "WashingMachineCoordinator":
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import entity_registry as er

    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError("Aucune integration Machine a laver intelligente n'est chargee")

    if entity_id is None:
        if len(coordinators) == 1:
            return coordinators[0]
        raise HomeAssistantError(
            "entity_id est obligatoire quand plusieurs integrations Machine a laver intelligente existent"
        )

    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)
    if entity_entry is None:
        raise HomeAssistantError(f"entity_id inconnue : {entity_id}")

    coordinator = hass.data.get(DOMAIN, {}).get(entity_entry.config_entry_id)
    if coordinator is None:
        raise HomeAssistantError(f"Aucun coordinateur trouve pour entity_id : {entity_id}")
    return coordinator
