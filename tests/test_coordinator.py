from __future__ import annotations

import sys
import types
import unittest
import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def _install_fake_homeassistant_modules() -> None:
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers_storage = types.ModuleType("homeassistant.helpers.storage")
    helpers_update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    util = types.ModuleType("homeassistant.util")
    util_dt = types.ModuleType("homeassistant.util.dt")

    class ConfigEntry:
        def __init__(self, *, data: dict, options: dict | None = None, entry_id: str = "test-entry", title: str = "Machine") -> None:
            self.data = data
            self.options = options or {}
            self.entry_id = entry_id
            self.title = title

    class HomeAssistant:
        pass

    class Store:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, _hass, _version, _key) -> None:
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, payload):
            self.data = payload

    class DataUpdateCoordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, hass, logger, name, update_interval) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None

        async def async_request_refresh(self) -> None:
            return None

        async def async_config_entry_first_refresh(self) -> None:
            return None

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    helpers_storage.Store = Store
    helpers_update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    util_dt.utcnow = lambda: datetime.now(timezone.utc)
    util.dt = util_dt

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.storage"] = helpers_storage
    sys.modules["homeassistant.helpers.update_coordinator"] = helpers_update_coordinator
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = util_dt


_install_fake_homeassistant_modules()

_real_dataclass = dataclasses.dataclass


def _compat_dataclass(*args, **kwargs):
    kwargs.pop("slots", None)
    return _real_dataclass(*args, **kwargs)


dataclasses.dataclass = _compat_dataclass

from homeassistant.config_entries import ConfigEntry

from custom_components.washing_machine_assistant.const import (
    CONF_POWER_SENSOR,
    STATUS_FINISHED,
    STATUS_IDLE,
    STATUS_RUNNING,
)
from custom_components.washing_machine_assistant.coordinator import (
    SourceSnapshot,
    WashingMachineCoordinator,
)
from custom_components.washing_machine_assistant.engine import InferenceResult, ProgramProfile


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeStates:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def get(self, entity_id: str):
        if not entity_id:
            return None
        value = self._mapping.get(entity_id)
        if value is None:
            return None
        return _FakeState(value)


class WashingMachineCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def _build_coordinator(self, states: dict[str, str]) -> WashingMachineCoordinator:
        hass = SimpleNamespace(states=_FakeStates(states), data={})
        entry = ConfigEntry(
            data={CONF_POWER_SENSOR: "sensor.machine_power"},
            options={},
            entry_id="entry-1",
            title="Machine a laver",
        )
        coordinator = WashingMachineCoordinator(hass, entry)
        coordinator._storage.async_save = AsyncMock()
        return coordinator

    async def test_read_sources_uses_cached_power_during_short_unavailability(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "unavailable"})
        now = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        coordinator._last_live_power_w = 42.0
        coordinator._last_live_power_at = now - timedelta(seconds=45)

        snapshot = coordinator._read_sources(now)

        self.assertEqual(snapshot.power_w, 42.0)
        self.assertEqual(snapshot.power_source, "cached")
        self.assertEqual(snapshot.power_unavailable_seconds, 45)

    async def test_start_calibration_begins_immediately_even_at_zero_watts(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        coordinator.data = SimpleNamespace(status=STATUS_IDLE, cycle_started_at=None)
        clicked_at = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)

        with patch("custom_components.washing_machine_assistant.coordinator.dt_util.utcnow", return_value=clicked_at):
            await coordinator.async_start_calibration()

        self.assertEqual(coordinator.calibration_state, "recording")
        self.assertEqual(coordinator.calibration_status_label, "En cours de calibration")
        self.assertEqual(coordinator._calibration_started_at, clicked_at)
        self.assertIsNone(coordinator._calibration_cycle_started_at)
        self.assertEqual(coordinator._calibration_power_samples, [0.0])

    async def test_finished_calibration_persists_profile_after_cycle_is_bound(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        started_at = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        cycle_started_at = started_at + timedelta(minutes=2)
        finished_at = cycle_started_at + timedelta(minutes=28)

        coordinator._begin_calibration_capture(
            started_at=started_at,
            cycle_started_at=None,
            snapshot=SourceSnapshot(power_w=0.0, vibration_on=False, door_open=None),
        )

        running_result = InferenceResult(
            available=True,
            status=STATUS_RUNNING,
            phase="starting",
            probable_program="unknown",
            program_label="Unknown",
            program_source="builtin",
            confidence="low",
            match_score=None,
            power_w=12.0,
            remaining_minutes=None,
            finish_time=None,
            cycle_started_at=cycle_started_at,
            last_activity_at=cycle_started_at,
            elapsed_minutes=0,
            observed_peak_power_w=12.0,
            diagnostics={},
        )
        await coordinator._async_handle_learning(
            running_result,
            SourceSnapshot(power_w=12.0, vibration_on=False, door_open=None),
        )

        profile = ProgramProfile(
            slug="learned_test_1",
            label="Mode appris test 1",
            min_duration_min=20,
            typical_duration_min=30,
            max_duration_min=40,
            source="learned",
            sample_count=1,
        )
        coordinator._build_learned_profile = lambda result: profile  # type: ignore[method-assign]
        coordinator._update_adaptive_thresholds_from_result = lambda result: None  # type: ignore[method-assign]

        finished_result = InferenceResult(
            available=True,
            status=STATUS_FINISHED,
            phase="finished",
            probable_program="unknown",
            program_label="Unknown",
            program_source="builtin",
            confidence="low",
            match_score=None,
            power_w=0.0,
            remaining_minutes=0,
            finish_time=finished_at,
            cycle_started_at=cycle_started_at,
            last_activity_at=finished_at,
            elapsed_minutes=28,
            observed_peak_power_w=226.0,
            diagnostics={"cycle_signature": {}, "high_power_samples": 0},
        )
        await coordinator._async_handle_learning(
            finished_result,
            SourceSnapshot(power_w=0.0, vibration_on=False, door_open=None),
        )

        self.assertEqual(coordinator._learned_profiles, [profile])
        self.assertEqual(coordinator.last_calibrated_profile, profile)
        self.assertFalse(coordinator._calibration_active)
        self.assertIsNone(coordinator._calibration_cycle_started_at)
        coordinator._storage.async_save.assert_awaited_once()

    async def test_initialize_restores_persisted_learning_metadata_and_finished_cycle(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        stored_profile = ProgramProfile(
            slug="learned_mix_60",
            label="Mix 60°",
            min_duration_min=54,
            typical_duration_min=66,
            max_duration_min=78,
            source="learned",
            sample_count=1,
        )
        finished_at = datetime(2026, 4, 5, 16, 46, 44, tzinfo=timezone.utc)
        coordinator._storage.async_load = AsyncMock(
            return_value={
                "learned_profiles": [dataclasses.asdict(stored_profile)],
                "adaptive_thresholds": {"start_power_w": 10.6, "stop_power_w": 3.7, "high_power_w": 1071.4},
                "last_calibrated_slug": "learned_mix_60",
                "last_calibrated_at": "2026-04-05T16:52:14.359372+00:00",
                "completed_at": "2026-04-05T16:52:14.359372+00:00",
                "completed_result": {
                    "available": True,
                    "status": "finished",
                    "phase": "finished",
                    "probable_program": "learned_mix_60",
                    "program_label": "Mix 60°",
                    "program_source": "learned",
                    "confidence": "high",
                    "match_score": 88,
                    "power_w": 0.0,
                    "remaining_minutes": 0,
                    "finish_time": finished_at.isoformat(),
                    "cycle_started_at": "2026-04-05T15:43:14.358068+00:00",
                    "last_activity_at": finished_at.isoformat(),
                    "elapsed_minutes": 63,
                    "observed_peak_power_w": 1995.0,
                    "diagnostics": {},
                },
            }
        )

        await coordinator.async_initialize()

        self.assertEqual(coordinator.learned_profiles[0].label, "Mix 60°")
        self.assertEqual(coordinator.last_calibrated_profile.slug, "learned_mix_60")
        self.assertEqual(coordinator.last_calibrated_at.isoformat(), "2026-04-05T16:52:14.359372+00:00")
        self.assertEqual(coordinator.adaptive_thresholds["start_power_w"], 10.6)
        self.assertEqual(coordinator._engine.completed_result.probable_program, "learned_mix_60")

    async def test_initialize_restores_runtime_cycle_and_calibration_state(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "120"})
        cycle_started_at = datetime(2026, 4, 5, 17, 15, tzinfo=timezone.utc)
        coordinator._storage.async_load = AsyncMock(
            return_value={
                "runtime_state": {
                    "cycle_started_at": cycle_started_at.isoformat(),
                    "last_activity_at": (cycle_started_at + timedelta(minutes=20)).isoformat(),
                    "inactive_since": None,
                    "observed_peak_power_w": 1988.0,
                    "high_power_samples": 15,
                    "spin_like_samples": 0,
                    "power_window": [55.0, 72.0, 94.0],
                    "cycle_power_samples": [0.0, 12.0, 15.0, 1880.0, 95.0],
                    "cycle_vibration_samples": [False, False, False, False, False],
                    "locked_profile_slug": "learned_mix_60",
                    "locked_profile_score": 22.0,
                    "best_candidate_slug": "learned_mix_60",
                    "best_candidate_score": 22.0,
                    "locked_phase": "washing",
                    "pending_phase": None,
                    "pending_phase_count": 0,
                    "estimated_total_minutes": 66,
                },
                "calibration_state": {
                    "active": True,
                    "started_at": cycle_started_at.isoformat(),
                    "cycle_started_at": cycle_started_at.isoformat(),
                    "power_samples": [0.0, 12.0, 15.0, 1880.0],
                    "vibration_samples": [False, False, False, False],
                },
                "last_processed_cycle_key": "learned_mix_60|2026-04-05T18:20:38+00:00",
            }
        )

        await coordinator.async_initialize()

        runtime = coordinator._engine.export_runtime_state()
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime["cycle_started_at"], cycle_started_at)
        self.assertEqual(runtime["locked_profile_slug"], "learned_mix_60")
        self.assertEqual(coordinator.calibration_state, "recording")
        self.assertEqual(coordinator._calibration_power_samples, [0.0, 12.0, 15.0, 1880.0])
        self.assertEqual(coordinator._last_processed_cycle_key, "learned_mix_60|2026-04-05T18:20:38+00:00")

    async def test_finished_unknown_cycle_creates_new_learned_profile_automatically(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        coordinator._learned_profiles = [
            ProgramProfile(
                slug="learned_mix_60",
                label="Mix 60°",
                min_duration_min=54,
                typical_duration_min=66,
                max_duration_min=78,
                source="learned",
                sample_count=1,
            )
        ]
        coordinator._engine.set_learned_profiles(coordinator._learned_profiles)

        profile = ProgramProfile(
            slug="learned_mode_auto_2",
            label="Mode auto 2",
            min_duration_min=58,
            typical_duration_min=70,
            max_duration_min=82,
            source="learned",
            sample_count=1,
        )
        coordinator._build_learned_profile = lambda result, auto_created=False: profile  # type: ignore[method-assign]
        coordinator._update_adaptive_thresholds_from_result = lambda result: None  # type: ignore[method-assign]

        finished_at = datetime(2026, 4, 5, 18, 20, 38, tzinfo=timezone.utc)
        finished_result = InferenceResult(
            available=True,
            status=STATUS_FINISHED,
            phase="finished",
            probable_program="unknown",
            program_label="Inconnu",
            program_source="builtin",
            confidence="low",
            match_score=44,
            power_w=0.0,
            remaining_minutes=0,
            finish_time=finished_at,
            cycle_started_at=finished_at - timedelta(minutes=70),
            last_activity_at=finished_at,
            elapsed_minutes=70,
            observed_peak_power_w=1995.0,
            diagnostics={
                "power_source": "live",
                "cycle_signature": {"signature": [10, 25, 100, 18, 22, 35]},
                "high_power_samples": 12,
            },
        )

        await coordinator._async_handle_learning(
            finished_result,
            SourceSnapshot(power_w=0.0, vibration_on=False, door_open=None),
        )

        self.assertEqual(coordinator.learned_profiles[-1], profile)
        self.assertEqual(coordinator.last_auto_learned_profile, profile)
        self.assertIsNotNone(coordinator.last_auto_learned_at)
        coordinator._storage.async_save.assert_awaited_once()

    async def test_delete_learned_profile_removes_mode_and_clears_last_refs(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        profile = ProgramProfile(
            slug="learned_mix_60",
            label="Mix 60°",
            min_duration_min=54,
            typical_duration_min=66,
            max_duration_min=78,
            source="learned",
            sample_count=1,
        )
        coordinator._learned_profiles = [profile]
        coordinator._last_calibrated_profile = profile
        coordinator._last_calibrated_at = datetime(2026, 4, 5, 16, 52, tzinfo=timezone.utc)

        deleted = await coordinator.async_delete_learned_profile("learned_mix_60")

        self.assertTrue(deleted)
        self.assertEqual(coordinator.learned_profiles, [])
        self.assertIsNone(coordinator.last_calibrated_profile)
        self.assertIsNone(coordinator.last_calibrated_at)
        coordinator._storage.async_save.assert_awaited_once()

    async def test_merge_learned_profiles_keeps_target_and_combines_samples(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        target = ProgramProfile(
            slug="learned_mix",
            label="MIX",
            min_duration_min=60,
            typical_duration_min=66,
            max_duration_min=78,
            source="learned",
            sample_count=2,
            peak_power_w=1900.0,
            uses_heating=True,
        )
        source = ProgramProfile(
            slug="learned_mix_40",
            label="Mix 40",
            min_duration_min=54,
            typical_duration_min=60,
            max_duration_min=72,
            source="learned",
            sample_count=1,
            peak_power_w=1750.0,
            uses_heating=True,
        )
        coordinator._learned_profiles = [target, source]

        merged = await coordinator.async_merge_learned_profiles("learned_mix_40", "learned_mix")

        self.assertTrue(merged)
        self.assertEqual(len(coordinator.learned_profiles), 1)
        self.assertEqual(coordinator.learned_profiles[0].slug, "learned_mix")
        self.assertEqual(coordinator.learned_profiles[0].sample_count, 3)
        coordinator._storage.async_save.assert_awaited_once()

    async def test_confirm_learned_profile_reinforces_last_completed_cycle(self) -> None:
        coordinator = self._build_coordinator({"sensor.machine_power": "0"})
        profile = ProgramProfile(
            slug="learned_mix",
            label="MIX",
            min_duration_min=60,
            typical_duration_min=66,
            max_duration_min=78,
            source="learned",
            sample_count=1,
        )
        coordinator._learned_profiles = [profile]
        coordinator._engine.set_learned_profiles(coordinator._learned_profiles)
        finished_at = datetime(2026, 4, 5, 18, 20, 38, tzinfo=timezone.utc)
        coordinator._engine.restore_completed_cycle(
            InferenceResult(
                available=True,
                status=STATUS_FINISHED,
                phase="finished",
                probable_program="unknown",
                program_label="Inconnu",
                program_source="builtin",
                confidence="low",
                match_score=41,
                power_w=0.0,
                remaining_minutes=0,
                finish_time=finished_at,
                cycle_started_at=finished_at - timedelta(minutes=66),
                last_activity_at=finished_at,
                elapsed_minutes=66,
                observed_peak_power_w=1990.0,
                diagnostics={"cycle_signature": {"signature": [10, 20, 100, 20, 10, 5]}, "high_power_samples": 12},
            ),
            finished_at,
        )

        confirmed = await coordinator.async_confirm_learned_profile("learned_mix")

        self.assertTrue(confirmed)
        self.assertEqual(coordinator._engine.completed_result.probable_program, "learned_mix")
        self.assertEqual(coordinator._engine.completed_result.program_label, "MIX")
        self.assertEqual(coordinator.last_auto_learned_profile.slug, "learned_mix")
        coordinator._storage.async_save.assert_awaited()


if __name__ == "__main__":
    unittest.main()
