from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .engine import InferenceResult, ProgramProfile

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
        last_calibrated_slug: str | None = None,
        last_calibrated_at: datetime | None = None,
        last_auto_learned_slug: str | None = None,
        last_auto_learned_at: datetime | None = None,
        completed_result: InferenceResult | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        payload = {
            "learned_profiles": [asdict(profile) for profile in learned_profiles],
            "adaptive_thresholds": adaptive_thresholds or {},
            "last_calibrated_slug": last_calibrated_slug,
            "last_calibrated_at": None if last_calibrated_at is None else last_calibrated_at.isoformat(),
            "last_auto_learned_slug": last_auto_learned_slug,
            "last_auto_learned_at": None if last_auto_learned_at is None else last_auto_learned_at.isoformat(),
            "completed_result": self._serialize_inference_result(completed_result),
            "completed_at": None if completed_at is None else completed_at.isoformat(),
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

    @staticmethod
    def parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @classmethod
    def parse_inference_result(cls, data: dict[str, Any]) -> InferenceResult | None:
        raw = data.get("completed_result")
        if not isinstance(raw, dict):
            return None

        try:
            payload = dict(raw)
            for key in ("finish_time", "cycle_started_at", "last_activity_at"):
                payload[key] = cls.parse_datetime(payload.get(key))
            diagnostics = payload.get("diagnostics")
            if not isinstance(diagnostics, dict):
                payload["diagnostics"] = {}
            return InferenceResult(**payload)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_inference_result(result: InferenceResult | None) -> dict[str, Any] | None:
        if result is None:
            return None
        payload = asdict(result)
        for key in ("finish_time", "cycle_started_at", "last_activity_at"):
            value = payload.get(key)
            payload[key] = None if value is None else value.isoformat()
        return payload
