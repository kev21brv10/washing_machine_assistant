from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import timedelta
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DOOR_SENSOR,
    CONF_FINISH_GRACE_MINUTES,
    CONF_HIGH_POWER_W,
    CONF_POWER_SENSOR,
    CONF_RESET_FINISHED_MINUTES,
    CONF_START_POWER_W,
    CONF_STOP_POWER_W,
    CONF_UPDATE_INTERVAL_SECONDS,
    CONF_VIBRATION_SENSOR,
    DEFAULT_FINISH_GRACE_MINUTES,
    DEFAULT_HIGH_POWER_W,
    DEFAULT_RESET_FINISHED_MINUTES,
    DEFAULT_START_POWER_W,
    DEFAULT_STOP_POWER_W,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    PROGRAM_SOURCE_LEARNED,
    PROGRAM_UNKNOWN,
    STATUS_RUNNING,
)
from .engine import InferenceResult, MachineTelemetry, ProgramProfile, WashingMachineInferenceEngine
from .storage import WashingMachineStorage

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceSnapshot:
    power_w: float | None
    vibration_on: bool
    door_open: bool | None
    power_source: str = "live"
    power_unavailable_seconds: int = 0


class WashingMachineCoordinator(DataUpdateCoordinator[InferenceResult]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._storage = WashingMachineStorage(hass, entry.entry_id)
        self._learned_profiles: list[ProgramProfile] = []
        self._calibration_armed = False
        self._calibration_active = False
        self._calibration_started_at = None
        self._calibration_cycle_started_at = None
        self._calibration_power_samples: list[float] = []
        self._calibration_vibration_samples: list[bool] = []
        self._last_calibrated_profile: ProgramProfile | None = None
        self._last_calibrated_at = None
        self._last_auto_learned_profile: ProgramProfile | None = None
        self._last_auto_learned_at = None
        self._last_processed_cycle_key: str | None = None
        self._auto_learning_min_score = 78
        self._base_start_power_w = float(entry.options.get(CONF_START_POWER_W, entry.data.get(CONF_START_POWER_W, DEFAULT_START_POWER_W)))
        self._base_stop_power_w = float(entry.options.get(CONF_STOP_POWER_W, entry.data.get(CONF_STOP_POWER_W, DEFAULT_STOP_POWER_W)))
        self._base_high_power_w = float(entry.options.get(CONF_HIGH_POWER_W, entry.data.get(CONF_HIGH_POWER_W, DEFAULT_HIGH_POWER_W)))
        self._adaptive_thresholds: dict[str, float] = {}
        self._last_live_power_w: float | None = None
        self._last_live_power_at = None
        self._engine = WashingMachineInferenceEngine(
            start_power_w=self._base_start_power_w,
            stop_power_w=self._base_stop_power_w,
            high_power_w=self._base_high_power_w,
            finish_grace_minutes=int(
                entry.options.get(
                    CONF_FINISH_GRACE_MINUTES,
                    entry.data.get(CONF_FINISH_GRACE_MINUTES, DEFAULT_FINISH_GRACE_MINUTES),
                )
            ),
            reset_finished_minutes=int(
                entry.options.get(
                    CONF_RESET_FINISHED_MINUTES,
                    entry.data.get(CONF_RESET_FINISHED_MINUTES, DEFAULT_RESET_FINISHED_MINUTES),
                )
            ),
        )
        update_interval = timedelta(
            seconds=int(
                entry.options.get(
                    CONF_UPDATE_INTERVAL_SECONDS,
                    entry.data.get(CONF_UPDATE_INTERVAL_SECONDS, DEFAULT_UPDATE_INTERVAL_SECONDS),
                )
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=update_interval,
        )
        self._power_fallback_ttl = max(timedelta(seconds=90), update_interval * 4)

    async def async_initialize(self) -> None:
        payload = await self._storage.async_load()
        self._learned_profiles = self._sort_profiles(self._storage.parse_profiles(payload))
        self._adaptive_thresholds = self._storage.parse_adaptive_thresholds(payload)
        self._engine.set_learned_profiles(self._learned_profiles)
        self._apply_runtime_thresholds()

    async def _async_update_data(self) -> InferenceResult:
        now = dt_util.utcnow()
        snapshot = self._read_sources(now)
        result = self._engine.update(
            MachineTelemetry(
                timestamp=now,
                power_w=snapshot.power_w,
                vibration_on=snapshot.vibration_on,
                door_open=snapshot.door_open,
            )
        )
        result = replace(
            result,
            diagnostics={
                **result.diagnostics,
                "power_source": snapshot.power_source,
                "power_unavailable_seconds": snapshot.power_unavailable_seconds,
            },
        )
        await self._async_handle_learning(result, snapshot)
        return result

    def _read_sources(self, now=None) -> SourceSnapshot:
        now = now or dt_util.utcnow()
        power_state = self.hass.states.get(self.entry.data[CONF_POWER_SENSOR])
        vibration_state = self.hass.states.get(self.entry.data.get(CONF_VIBRATION_SENSOR, ""))
        door_state = self.hass.states.get(self.entry.data.get(CONF_DOOR_SENSOR, ""))

        power_w = self._parse_float_state(power_state.state if power_state else None)
        vibration_on = self._parse_bool_state(vibration_state.state if vibration_state else None)
        door_open = None if door_state is None else self._parse_bool_state(door_state.state)
        if power_w is not None:
            self._last_live_power_w = power_w
            self._last_live_power_at = now
            return SourceSnapshot(power_w=power_w, vibration_on=vibration_on, door_open=door_open)

        if (
            self._last_live_power_w is not None
            and self._last_live_power_at is not None
            and now - self._last_live_power_at <= self._power_fallback_ttl
        ):
            return SourceSnapshot(
                power_w=self._last_live_power_w,
                vibration_on=vibration_on,
                door_open=door_open,
                power_source="cached",
                power_unavailable_seconds=int((now - self._last_live_power_at).total_seconds()),
            )

        return SourceSnapshot(power_w=None, vibration_on=vibration_on, door_open=door_open, power_source="missing")

    @staticmethod
    def _parse_float_state(value: str | None) -> float | None:
        if value in {None, "unknown", "unavailable", ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_bool_state(value: str | None) -> bool:
        return value in {"on", "open", "true", "home", "detected"}

    async def async_start_calibration(self) -> None:
        snapshot = self._read_sources()
        running_cycle_started_at = None
        if self.data is not None and self.data.status == STATUS_RUNNING:
            running_cycle_started_at = self.data.cycle_started_at
        self._calibration_armed = False
        self._begin_calibration_capture(
            started_at=dt_util.utcnow(),
            cycle_started_at=running_cycle_started_at,
            snapshot=snapshot,
        )
        await self.async_request_refresh()

    async def async_rename_learned_profile(self, mode_slug: str, new_name: str) -> bool:
        cleaned_name = new_name.strip()
        if not cleaned_name:
            return False

        updated = False
        renamed_profiles: list[ProgramProfile] = []
        for profile in self._learned_profiles:
            if profile.slug == mode_slug:
                renamed_profiles.append(replace(profile, label=cleaned_name))
                updated = True
            else:
                renamed_profiles.append(profile)

        if not updated:
            return False

        self._learned_profiles = self._sort_profiles(renamed_profiles)
        self._engine.set_learned_profiles(self._learned_profiles)
        await self._storage.async_save(
            learned_profiles=self._learned_profiles,
            adaptive_thresholds=self._adaptive_thresholds,
        )

        if self._last_calibrated_profile and self._last_calibrated_profile.slug == mode_slug:
            self._last_calibrated_profile = replace(self._last_calibrated_profile, label=cleaned_name)

        await self.async_request_refresh()
        return True

    async def _async_handle_learning(self, result: InferenceResult, snapshot: SourceSnapshot) -> None:
        if self._calibration_active and self._calibration_cycle_started_at is None:
            if result.status == STATUS_RUNNING and result.cycle_started_at is not None:
                self._calibration_cycle_started_at = result.cycle_started_at

        if self._calibration_active:
            self._append_calibration_sample(snapshot)

        cycle_key = self._cycle_key(result)
        if cycle_key is None:
            return
        if cycle_key == self._last_processed_cycle_key:
            return

        if not self._calibration_active:
            await self._async_handle_auto_learning(result, cycle_key)
            return

        if result.status != "finished":
            return

        if self._calibration_cycle_started_at is None:
            return

        if result.cycle_started_at != self._calibration_cycle_started_at:
            return

        profile = self._build_learned_profile(result)
        self._learned_profiles.append(profile)
        self._learned_profiles = self._sort_profiles(self._learned_profiles)
        self._engine.set_learned_profiles(self._learned_profiles)
        self._update_adaptive_thresholds_from_result(result)
        await self._storage.async_save(
            learned_profiles=self._learned_profiles,
            adaptive_thresholds=self._adaptive_thresholds,
        )
        self._last_calibrated_profile = profile
        self._last_calibrated_at = dt_util.utcnow()
        self._reset_calibration_capture()
        self._last_processed_cycle_key = cycle_key

    async def _async_handle_auto_learning(self, result: InferenceResult, cycle_key: str) -> None:
        if result.status != "finished":
            return
        if result.program_source != PROGRAM_SOURCE_LEARNED:
            return
        if (result.match_score or 0) < self._auto_learning_min_score:
            return

        updated = await self._async_update_existing_profile(result.probable_program, result)
        if not updated:
            return
        self._last_processed_cycle_key = cycle_key

    async def _async_update_existing_profile(self, mode_slug: str, result: InferenceResult) -> bool:
        updated = False
        merged_profiles: list[ProgramProfile] = []
        features = self._features_from_result(result)
        from .engine import merge_profile

        for profile in self._learned_profiles:
            if profile.slug == mode_slug:
                merged = merge_profile(profile, features)
                merged_profiles.append(merged)
                self._last_auto_learned_profile = merged
                self._last_auto_learned_at = dt_util.utcnow()
                updated = True
            else:
                merged_profiles.append(profile)

        if not updated:
            return False

        self._learned_profiles = self._sort_profiles(merged_profiles)
        self._engine.set_learned_profiles(self._learned_profiles)
        self._update_adaptive_thresholds_from_result(result)
        await self._storage.async_save(
            learned_profiles=self._learned_profiles,
            adaptive_thresholds=self._adaptive_thresholds,
        )
        return True

    def _build_learned_profile(self, result: InferenceResult) -> ProgramProfile:
        finish_time = result.finish_time or result.last_activity_at or dt_util.utcnow()
        if self._calibration_started_at is not None:
            duration = max(1, int((finish_time - self._calibration_started_at).total_seconds() // 60))
        else:
            duration = max(1, result.elapsed_minutes or 0)

        if self._calibration_power_samples:
            cycle_signature = self._engine.build_cycle_signature(
                self._calibration_power_samples,
                self._calibration_vibration_samples,
            )
            peak_power_w = max(self._calibration_power_samples)
            heating_threshold = self._adaptive_thresholds.get("high_power_w", self._base_high_power_w)
            uses_heating = any(sample >= heating_threshold for sample in self._calibration_power_samples)
        else:
            cycle_signature = result.diagnostics.get("cycle_signature", {})
            peak_power_w = result.observed_peak_power_w or None
            uses_heating = (result.diagnostics.get("high_power_samples", 0) > 0)

        base_slug = self._slugify(result.program_label if result.probable_program != PROGRAM_UNKNOWN else "mode_appris")
        if not base_slug:
            base_slug = "mode_appris"
        slug = f"learned_{base_slug}_{len(self._learned_profiles) + 1}"
        if result.probable_program != PROGRAM_UNKNOWN:
            label = f"Mode appris {result.program_label.lower()} {len(self._learned_profiles) + 1}"
        else:
            label = f"Mode appris {len(self._learned_profiles) + 1}"
        return ProgramProfile(
            slug=slug,
            label=label,
            min_duration_min=max(1, duration - 12),
            typical_duration_min=duration,
            max_duration_min=duration + 12,
            source=PROGRAM_SOURCE_LEARNED,
            sample_count=1,
            peak_power_w=peak_power_w,
            uses_heating=uses_heating,
            avg_power_w=cycle_signature.get("avg_power_w"),
            high_power_ratio=cycle_signature.get("high_power_ratio"),
            spin_ratio=cycle_signature.get("spin_ratio"),
            signature=cycle_signature.get("signature"),
        )

    @staticmethod
    def _features_from_result(result: InferenceResult):
        from .engine import CycleFeatures

        cycle_signature = result.diagnostics.get("cycle_signature", {})
        return CycleFeatures(
            duration_min=max(1, result.elapsed_minutes or 0),
            peak_power_w=result.observed_peak_power_w or None,
            uses_heating=(result.diagnostics.get("high_power_samples", 0) > 0),
            avg_power_w=cycle_signature.get("avg_power_w"),
            high_power_ratio=cycle_signature.get("high_power_ratio"),
            spin_ratio=cycle_signature.get("spin_ratio"),
            signature=cycle_signature.get("signature"),
            start_power_w=cycle_signature.get("start_power_w"),
            stop_power_w=cycle_signature.get("stop_power_w"),
        )

    @staticmethod
    def _cycle_key(result: InferenceResult) -> str | None:
        if result.status != "finished" or result.finish_time is None:
            return None
        return f"{result.probable_program}|{result.finish_time.isoformat()}"

    @staticmethod
    def _sort_profiles(profiles: list[ProgramProfile]) -> list[ProgramProfile]:
        return sorted(profiles, key=lambda item: (item.typical_duration_min, item.slug))

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    def _apply_runtime_thresholds(self) -> None:
        self._engine.set_runtime_thresholds(
            start_power_w=self._adaptive_thresholds.get("start_power_w", self._base_start_power_w),
            stop_power_w=self._adaptive_thresholds.get("stop_power_w", self._base_stop_power_w),
            high_power_w=self._adaptive_thresholds.get("high_power_w", self._base_high_power_w),
        )

    def _begin_calibration_capture(
        self,
        *,
        started_at,
        cycle_started_at,
        snapshot: SourceSnapshot,
    ) -> None:
        self._calibration_active = True
        self._calibration_started_at = started_at
        self._calibration_cycle_started_at = cycle_started_at
        self._calibration_power_samples = []
        self._calibration_vibration_samples = []
        self._append_calibration_sample(snapshot)

    def _append_calibration_sample(self, snapshot: SourceSnapshot) -> None:
        if snapshot.power_w is None:
            return
        self._calibration_power_samples.append(snapshot.power_w)
        self._calibration_vibration_samples.append(snapshot.vibration_on)

    def _reset_calibration_capture(self) -> None:
        self._calibration_armed = False
        self._calibration_active = False
        self._calibration_started_at = None
        self._calibration_cycle_started_at = None
        self._calibration_power_samples = []
        self._calibration_vibration_samples = []

    def _update_adaptive_thresholds_from_result(self, result: InferenceResult) -> None:
        cycle_signature = result.diagnostics.get("cycle_signature", {})
        suggested_start = cycle_signature.get("start_power_w")
        suggested_stop = cycle_signature.get("stop_power_w")
        peak_power = result.observed_peak_power_w or 0.0
        avg_power = cycle_signature.get("avg_power_w") or 0.0
        suggested_heat = None
        if peak_power > 0:
            suggested_heat = round(
                max(
                    peak_power * 0.6,
                    avg_power * 1.35,
                    self._adaptive_thresholds.get("start_power_w", self._base_start_power_w) * 4,
                ),
                1,
            )

        self._adaptive_thresholds["start_power_w"] = self._merge_threshold(
            self._adaptive_thresholds.get("start_power_w", self._base_start_power_w),
            suggested_start,
            minimum=4.0,
            maximum=40.0,
        )
        self._adaptive_thresholds["stop_power_w"] = self._merge_threshold(
            self._adaptive_thresholds.get("stop_power_w", self._base_stop_power_w),
            suggested_stop,
            minimum=1.0,
            maximum=15.0,
        )
        self._adaptive_thresholds["high_power_w"] = self._merge_threshold(
            self._adaptive_thresholds.get("high_power_w", self._base_high_power_w),
            suggested_heat,
            minimum=40.0,
            maximum=2500.0,
        )
        self._apply_runtime_thresholds()

    @staticmethod
    def _merge_threshold(
        current: float,
        observed: float | None,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        if observed is None:
            return current
        merged = round((current * 0.8) + (observed * 0.2), 1)
        return max(minimum, min(maximum, merged))

    @property
    def calibration_state(self) -> str:
        if self._calibration_active:
            return "recording"
        if self._calibration_armed:
            return "armed"
        return "idle"

    @property
    def calibration_status_label(self) -> str:
        if self._calibration_active:
            return "En cours de calibration"
        if self._calibration_armed:
            return "Calibration armee"
        return "Inactive"

    @property
    def learned_profiles(self) -> list[ProgramProfile]:
        return list(self._learned_profiles)

    @property
    def last_calibrated_profile(self) -> ProgramProfile | None:
        return self._last_calibrated_profile

    @property
    def last_calibrated_at(self):
        return self._last_calibrated_at

    @property
    def learned_modes_summary(self) -> list[dict[str, str | int | None]]:
        return [
            {
                "slug": profile.slug,
                "label": profile.label,
                "duration_min": profile.typical_duration_min,
                "sample_count": profile.sample_count,
                "has_signature": bool(profile.signature),
            }
            for profile in self._learned_profiles
        ]

    @property
    def last_auto_learned_profile(self) -> ProgramProfile | None:
        return self._last_auto_learned_profile

    @property
    def last_auto_learned_at(self):
        return self._last_auto_learned_at

    @property
    def adaptive_thresholds(self) -> dict[str, float]:
        return dict(self._adaptive_thresholds)
