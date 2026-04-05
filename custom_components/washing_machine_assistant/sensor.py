from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .const import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    PHASE_COOLDOWN,
    PHASE_FINISHED,
    PHASE_HEATING,
    PHASE_IDLE,
    PHASE_RINSING,
    PHASE_SPINNING,
    PHASE_STARTING,
    PHASE_UNKNOWN,
    PHASE_WASHING,
    PROGRAM_SOURCE_BUILTIN,
    PROGRAM_SOURCE_LEARNED,
    STATUS_FINISHED,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNAVAILABLE,
)
from .coordinator import WashingMachineCoordinator

STATUS_LABELS: dict[str, str] = {
    STATUS_IDLE: "Inactif",
    STATUS_RUNNING: "En cours",
    STATUS_FINISHED: "Termine",
    STATUS_UNAVAILABLE: "Indisponible",
}

PHASE_LABELS: dict[str, str] = {
    PHASE_IDLE: "Inactif",
    PHASE_STARTING: "Demarrage",
    PHASE_HEATING: "Chauffe",
    PHASE_WASHING: "Lavage",
    PHASE_RINSING: "Rincage",
    PHASE_SPINNING: "Essorage",
    PHASE_COOLDOWN: "Retour au calme",
    PHASE_FINISHED: "Termine",
    PHASE_UNKNOWN: "Inconnu",
}

CONFIDENCE_LABELS: dict[str, str] = {
    CONFIDENCE_LOW: "Faible",
    CONFIDENCE_MEDIUM: "Moyenne",
    CONFIDENCE_HIGH: "Elevee",
}

PROGRAM_SOURCE_LABELS: dict[str, str] = {
    PROGRAM_SOURCE_BUILTIN: "Profil integre",
    PROGRAM_SOURCE_LEARNED: "Mode appris",
}


@dataclass(frozen=True, kw_only=True)
class WashingMachineSensorDescription(SensorEntityDescription):
    value_key: str


SENSORS: tuple[WashingMachineSensorDescription, ...] = (
    WashingMachineSensorDescription(
        key="calibration_status",
        translation_key="calibration_status",
        value_key="calibration_status",
        icon="mdi:record-rec",
    ),
    WashingMachineSensorDescription(
        key="status",
        translation_key="status",
        value_key="status",
        icon="mdi:washing-machine",
    ),
    WashingMachineSensorDescription(
        key="phase",
        translation_key="phase",
        value_key="phase",
        icon="mdi:tune-vertical-variant",
    ),
    WashingMachineSensorDescription(
        key="program",
        translation_key="program",
        value_key="program_label",
        icon="mdi:washing-machine-alert",
    ),
    WashingMachineSensorDescription(
        key="remaining_time",
        translation_key="remaining_time",
        value_key="remaining_minutes",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    WashingMachineSensorDescription(
        key="finish_time",
        translation_key="finish_time",
        value_key="finish_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-end",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    coordinator: WashingMachineCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WashingMachineSensor(coordinator, entry, description) for description in SENSORS)


class WashingMachineSensor(CoordinatorEntity[WashingMachineCoordinator], SensorEntity):
    entity_description: WashingMachineSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WashingMachineCoordinator,
        entry: ConfigEntry,
        description: WashingMachineSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.available

    @property
    def native_value(self):
        if self.entity_description.value_key == "calibration_status":
            return self.coordinator.calibration_status_label
        value = getattr(self.coordinator.data, self.entity_description.value_key)
        if self.entity_description.key == "status":
            return STATUS_LABELS.get(value, value)
        if self.entity_description.key == "phase":
            return PHASE_LABELS.get(value, value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "confidence": data.confidence,
            "confidence_label": CONFIDENCE_LABELS.get(data.confidence, data.confidence),
            "match_score": data.match_score,
            "program_slug": data.probable_program,
            "program_source": data.program_source,
            "program_source_label": PROGRAM_SOURCE_LABELS.get(data.program_source, data.program_source),
            "power_w": data.power_w,
            "power_source": data.diagnostics.get("power_source"),
            "power_unavailable_seconds": data.diagnostics.get("power_unavailable_seconds", 0),
            "elapsed_minutes": data.elapsed_minutes,
            "cycle_started_at": data.cycle_started_at,
            "last_activity_at": data.last_activity_at,
            "observed_peak_power_w": data.observed_peak_power_w,
            "status_raw": data.status,
            "phase_raw": data.phase,
            "calibration_state": self.coordinator.calibration_state,
            "calibration_status": self.coordinator.calibration_status_label,
            "learned_modes_count": len(self.coordinator.learned_profiles),
            "learned_modes": self.coordinator.learned_modes_summary,
            "last_calibrated_mode": None
            if self.coordinator.last_calibrated_profile is None
            else self.coordinator.last_calibrated_profile.label,
            "last_calibrated_at": self.coordinator.last_calibrated_at,
            "last_auto_learned_mode": None
            if self.coordinator.last_auto_learned_profile is None
            else self.coordinator.last_auto_learned_profile.label,
            "last_auto_learned_at": self.coordinator.last_auto_learned_at,
            "adaptive_thresholds": self.coordinator.adaptive_thresholds,
            "diagnostics": data.diagnostics,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Custom",
            model="Machine a laver intelligente",
        )
