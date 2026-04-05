from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from custom_components.washing_machine_assistant.engine import (
    CycleFeatures,
    MachineTelemetry,
    ProgramProfile,
    WashingMachineInferenceEngine,
    merge_profile,
)


class WashingMachineInferenceEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = WashingMachineInferenceEngine(
            start_power_w=8.0,
            stop_power_w=3.0,
            high_power_w=1200.0,
            finish_grace_minutes=5,
            reset_finished_minutes=180,
        )
        self.start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)

    def _run_samples(self, samples: list[tuple[int, float, bool, bool | None]]):
        result = None
        for minute, power, vibration, door_open in samples:
            result = self.engine.update(
                MachineTelemetry(
                    timestamp=self.start + timedelta(minutes=minute),
                    power_w=power,
                    vibration_on=vibration,
                    door_open=door_open,
                )
            )
        return result

    def test_quick_cycle_is_detected_and_finished(self) -> None:
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (5, 1800.0, False, None),
                (10, 210.0, True, None),
                (18, 180.0, True, None),
                (24, 40.0, False, None),
                (29, 75.0, True, None),
                (34, 0.5, False, None),
                (40, 0.2, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.probable_program, "quick")
        self.assertEqual(result.remaining_minutes, 0)

    def test_eco_cycle_gets_long_duration_profile(self) -> None:
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 10.0, False, None),
                (2, 12.0, False, None),
                (8, 1750.0, False, None),
                (20, 160.0, True, None),
                (60, 145.0, True, None),
                (120, 55.0, False, None),
                (175, 70.0, True, None),
                (205, 0.0, False, None),
                (211, 0.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.probable_program, "eco")

    def test_finished_state_resets_when_door_opens(self) -> None:
        self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (5, 1900.0, False, None),
                (15, 150.0, True, None),
                (30, 0.0, False, None),
                (36, 0.0, False, None),
            ]
        )
        result = self.engine.update(
            MachineTelemetry(
                timestamp=self.start + timedelta(minutes=37),
                power_w=0.0,
                vibration_on=False,
                door_open=True,
            )
        )
        self.assertEqual(result.status, "idle")

    def test_cycle_stays_running_below_start_threshold_until_stop_threshold_is_crossed(self) -> None:
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 12.0, False, None),
                (4, 4.0, False, None),
                (8, 4.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "running")
        self.assertEqual(result.phase, "cooldown")

    def test_cycle_finishes_after_finish_grace_once_power_drops_below_stop_threshold(self) -> None:
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 12.0, False, None),
                (4, 4.0, False, None),
                (6, 2.0, False, None),
                (12, 2.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "finished")

    def test_learned_profile_is_selected_when_duration_matches(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_coton_1",
                    label="Mode appris coton 1",
                    min_duration_min=85,
                    typical_duration_min=92,
                    max_duration_min=105,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1850.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1850.0, False, None),
                (20, 180.0, True, None),
                (45, 160.0, True, None),
                (70, 90.0, False, None),
                (91, 70.0, True, None),
                (96, 0.0, False, None),
                (102, 0.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.probable_program, "learned_coton_1")
        self.assertEqual(result.program_source, "learned")

    def test_closest_learned_profile_uses_signature_and_score(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mode_froid",
                    label="Mode appris froid",
                    min_duration_min=80,
                    typical_duration_min=95,
                    max_duration_min=110,
                    source="learned",
                    sample_count=1,
                    peak_power_w=300.0,
                    uses_heating=False,
                    avg_power_w=120.0,
                    high_power_ratio=0.0,
                    spin_ratio=0.20,
                    signature=[10, 20, 25, 30, 35, 30, 20, 18, 22, 35, 18, 5],
                ),
                ProgramProfile(
                    slug="learned_mode_chaud",
                    label="Mode appris chaud",
                    min_duration_min=80,
                    typical_duration_min=95,
                    max_duration_min=110,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1900.0,
                    uses_heating=True,
                    avg_power_w=420.0,
                    high_power_ratio=0.17,
                    spin_ratio=0.50,
                    signature=[1, 100, 12, 11, 6, 5],
                ),
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 220.0, True, None),
                (40, 210.0, True, None),
                (60, 120.0, False, None),
                (88, 90.0, True, None),
                (96, 0.0, False, None),
                (102, 0.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.probable_program, "learned_mode_chaud")
        self.assertGreaterEqual(result.match_score or 0, 60)
        self.assertEqual(result.program_source, "learned")

    def test_merge_profile_updates_existing_mode_progressively(self) -> None:
        profile = ProgramProfile(
            slug="learned_coton_40",
            label="Coton 40",
            min_duration_min=90,
            typical_duration_min=100,
            max_duration_min=112,
            source="learned",
            sample_count=1,
            peak_power_w=1800.0,
            uses_heating=True,
            avg_power_w=410.0,
            high_power_ratio=0.16,
            spin_ratio=0.35,
            signature=[5, 100, 30, 25, 20, 10],
        )
        merged = merge_profile(
            profile,
            CycleFeatures(
                duration_min=104,
                peak_power_w=1860.0,
                uses_heating=True,
                avg_power_w=430.0,
                high_power_ratio=0.18,
                spin_ratio=0.38,
                signature=[4, 100, 32, 27, 18, 11],
            ),
        )
        self.assertEqual(merged.sample_count, 2)
        self.assertEqual(merged.typical_duration_min, 102)
        self.assertEqual(merged.label, "Coton 40")
        self.assertIsNotNone(merged.signature)
        self.assertEqual(merged.signature[0], 4)

    def test_cycle_signature_exposes_adaptive_threshold_hints(self) -> None:
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 18.0, False, None),
                (5, 1800.0, False, None),
                (10, 220.0, True, None),
                (18, 160.0, True, None),
                (24, 50.0, False, None),
                (29, 70.0, True, None),
                (34, 0.5, False, None),
                (40, 0.2, False, None),
            ]
        )
        self.assertIsNotNone(result)
        signature = result.diagnostics["cycle_signature"]
        self.assertIn("start_power_w", signature)
        self.assertIn("stop_power_w", signature)
        self.assertGreater(signature["start_power_w"], 0)
        self.assertGreater(signature["stop_power_w"], 0)


if __name__ == "__main__":
    unittest.main()
