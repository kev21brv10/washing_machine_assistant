from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WashingMachineCoordinator


@dataclass(frozen=True, kw_only=True)
class WashingMachineBinarySensorDescription(BinarySensorEntityDescription):
    value_key: str


BINARY_SENSORS: tuple[WashingMachineBinarySensorDescription, ...] = (
    WashingMachineBinarySensorDescription(
        key="running",
        translation_key="running",
        value_key="is_running",
        icon="mdi:play-circle-outline",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    WashingMachineBinarySensorDescription(
        key="finished",
        translation_key="finished",
        value_key="is_finished",
        icon="mdi:check-circle-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    coordinator: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WashingMachineBinarySensor(coordinator, entry, description) for description in BINARY_SENSORS)


class WashingMachineBinarySensor(CoordinatorEntity[WashingMachineCoordinator], BinarySensorEntity):
    entity_description: WashingMachineBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WashingMachineCoordinator,
        entry: ConfigEntry,
        description: WashingMachineBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.available

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.data, self.entity_description.value_key))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Custom",
            model="Washing Machine Assistant",
        )
