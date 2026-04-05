from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WashingMachineCoordinator


BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="start_calibration",
        translation_key="start_calibration",
        icon="mdi:record-rec",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    coordinator: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WashingMachineButton(coordinator, entry, description) for description in BUTTONS)


class WashingMachineButton(CoordinatorEntity[WashingMachineCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WashingMachineCoordinator,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    async def async_press(self) -> None:
        await self.coordinator.async_start_calibration()

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        profile = self.coordinator.last_calibrated_profile
        return {
            "calibration_state": self.coordinator.calibration_state,
            "calibration_status": self.coordinator.calibration_status_label,
            "learned_modes_count": len(self.coordinator.learned_profiles),
            "last_calibrated_mode": None if profile is None else profile.label,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Custom",
            model="Machine a laver intelligente",
        )
