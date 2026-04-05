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

    async def async_save(self, *, learned_profiles: list[ProgramProfile]) -> None:
        payload = {
            "learned_profiles": [asdict(profile) for profile in learned_profiles],
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
