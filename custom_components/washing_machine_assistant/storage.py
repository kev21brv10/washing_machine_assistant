from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .engine import ProgramProfile

STORAGE_VERSION = 1


class WashingMachineStorage:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}")

    async def async_load(self) -> dict[str, Any]:
        data = await self._store.async_load()
        return data or {}

    async def async_save(
        self,
        *,
        learned_profiles: list[ProgramProfile],
        adaptive_thresholds: dict[str, float] | None = None,
    ) -> None:
        payload = {
            "learned_profiles": [asdict(profile) for profile in learned_profiles],
            "adaptive_thresholds": adaptive_thresholds or {},
        }
        await self._store.async_save(payload)

    @staticmethod
    def parse_profiles(data: dict[str, Any]) -> list[ProgramProfile]:
        profiles: list[ProgramProfile] = []
        for item in data.get("learned_profiles", []):
            try:
                profiles.append(ProgramProfile(**item))
            except TypeError:
                continue
        return profiles

    @staticmethod
    def parse_adaptive_thresholds(data: dict[str, Any]) -> dict[str, float]:
        raw = data.get("adaptive_thresholds", {})
        parsed: dict[str, float] = {}
        for key in ("start_power_w", "stop_power_w", "high_power_w"):
            value = raw.get(key)
            if isinstance(value, (int, float)):
                parsed[key] = float(value)
        return parsed
