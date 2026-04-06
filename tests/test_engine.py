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

    def test_builtin_profiles_are_ignored_once_learned_profiles_exist(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mix_60",
                    label="Mix 60°",
                    min_duration_min=55,
                    typical_duration_min=66,
                    max_duration_min=78,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1990.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 180.0, True, None),
                (40, 70.0, False, None),
                (60, 25.0, False, None),
                (66, 0.0, False, None),
                (72, 0.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.probable_program, "learned_mix_60")
        self.assertEqual(result.program_source, "learned")

    def test_unknown_is_returned_when_no_learned_profile_is_close_enough(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_court",
                    label="Court",
                    min_duration_min=30,
                    typical_duration_min=35,
                    max_duration_min=42,
                    source="learned",
                    sample_count=1,
                    peak_power_w=250.0,
                    uses_heating=False,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (25, 220.0, False, None),
                (45, 180.0, False, None),
                (60, 140.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.probable_program, "unknown")
        self.assertEqual(result.program_label, "Inconnu")
        self.assertIsNotNone(result.match_score)

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

    def test_stability_lock_keeps_previous_program_when_new_candidate_is_only_slightly_better(self) -> None:
        learned = ProgramProfile(
            slug="learned_mix_60",
            label="Mix 60",
            min_duration_min=60,
            typical_duration_min=66,
            max_duration_min=74,
            source="learned",
        )
        builtin = ProgramProfile(
            slug="synthetics",
            label="Synthetiques",
            min_duration_min=50,
            typical_duration_min=75,
            max_duration_min=100,
            source="builtin",
        )
        self.engine._learned_profiles = (learned,)  # type: ignore[attr-defined]
        self.engine._locked_profile_slug = learned.slug  # type: ignore[attr-defined]
        self.engine._locked_profile_score = 44.0  # type: ignore[attr-defined]

        profile, score = self.engine._stabilize_program_choice(  # type: ignore[attr-defined]
            elapsed_minutes=50,
            candidate_profile=builtin,
            candidate_score=38.5,
            scores_by_slug={
                learned.slug: 44.0,
                builtin.slug: 38.5,
            },
        )
        self.assertEqual(profile.slug, learned.slug)
        self.assertEqual(score, 44.0)

    def test_stability_lock_resists_switches_between_learned_profiles_mid_cycle(self) -> None:
        mix = ProgramProfile(
            slug="learned_mix",
            label="MIX",
            min_duration_min=60,
            typical_duration_min=66,
            max_duration_min=74,
            source="learned",
        )
        coton = ProgramProfile(
            slug="learned_coton",
            label="Coton",
            min_duration_min=40,
            typical_duration_min=48,
            max_duration_min=58,
            source="learned",
        )
        self.engine._learned_profiles = (mix, coton)  # type: ignore[attr-defined]
        self.engine._locked_profile_slug = mix.slug  # type: ignore[attr-defined]
        self.engine._locked_profile_score = 28.0  # type: ignore[attr-defined]

        profile, score = self.engine._stabilize_program_choice(  # type: ignore[attr-defined]
            elapsed_minutes=45,
            candidate_profile=coton,
            candidate_score=14.0,
            scores_by_slug={
                mix.slug: 28.0,
                coton.slug: 14.0,
            },
        )
        self.assertEqual(profile.slug, mix.slug)
        self.assertEqual(score, 28.0)

    def test_phase_hysteresis_prevents_single_sample_flips_between_washing_and_cooldown(self) -> None:
        self.engine._locked_phase = "washing"  # type: ignore[attr-defined]

        first = self.engine._stabilize_phase("cooldown")  # type: ignore[attr-defined]
        second = self.engine._stabilize_phase("washing")  # type: ignore[attr-defined]
        third = self.engine._stabilize_phase("cooldown")  # type: ignore[attr-defined]

        self.assertEqual(first, "washing")
        self.assertEqual(second, "washing")
        self.assertEqual(third, "washing")

    def test_spinning_is_detected_from_late_power_ramp_without_vibration_sensor(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mix",
                    label="MIX",
                    min_duration_min=60,
                    typical_duration_min=66,
                    max_duration_min=74,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1990.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 85.0, False, None),
                (30, 95.0, False, None),
                (40, 70.0, False, None),
                (50, 110.0, False, None),
                (54, 170.0, False, None),
                (56, 210.0, False, None),
                (58, 260.0, False, None),
                (60, 320.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.phase, "spinning")

    def test_mid_cycle_power_bump_does_not_become_spinning_too_early(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mix",
                    label="MIX",
                    min_duration_min=60,
                    typical_duration_min=66,
                    max_duration_min=74,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1990.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 85.0, False, None),
                (24, 180.0, False, None),
                (26, 210.0, False, None),
                (28, 160.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertNotEqual(result.phase, "spinning")

    def test_late_cycle_medium_power_is_classified_as_rinsing(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mix",
                    label="MIX",
                    min_duration_min=60,
                    typical_duration_min=66,
                    max_duration_min=74,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1990.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 120.0, False, None),
                (35, 110.0, False, None),
                (45, 75.0, False, None),
                (52, 40.0, False, None),
                (54, 38.0, False, None),
                (56, 36.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.phase, "rinsing")

    def test_late_cycle_low_power_is_classified_as_cooldown(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_mix",
                    label="MIX",
                    min_duration_min=60,
                    typical_duration_min=66,
                    max_duration_min=74,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1990.0,
                    uses_heating=True,
                )
            ]
        )
        result = self._run_samples(
            [
                (0, 0.0, False, None),
                (1, 12.0, False, None),
                (2, 15.0, False, None),
                (8, 1880.0, False, None),
                (20, 120.0, False, None),
                (35, 90.0, False, None),
                (50, 24.0, False, None),
                (58, 8.0, False, None),
                (60, 7.0, False, None),
                (62, 6.0, False, None),
            ]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.phase, "cooldown")

    def test_remaining_time_is_smoothed_instead_of_jumping_wildly(self) -> None:
        self.engine.set_learned_profiles(
            [
                ProgramProfile(
                    slug="learned_cycle_long",
                    label="Cycle long",
                    min_duration_min=90,
                    typical_duration_min=102,
                    max_duration_min=114,
                    source="learned",
                    sample_count=1,
                    peak_power_w=1980.0,
                    uses_heating=True,
                )
            ]
        )
        checkpoints = [
            (0, 0.0, False, None),
            (1, 12.0, False, None),
            (2, 15.0, False, None),
            (8, 1880.0, False, None),
            (20, 95.0, False, None),
            (30, 120.0, False, None),
            (40, 55.0, False, None),
        ]
        result = self._run_samples(checkpoints)
        self.assertIsNotNone(result)
        first_remaining = result.remaining_minutes
        result = self.engine.update(
            MachineTelemetry(
                timestamp=self.start + timedelta(minutes=41),
                power_w=20.0,
                vibration_on=False,
                door_open=None,
            )
        )
        self.assertIsNotNone(result.remaining_minutes)
        self.assertGreaterEqual(result.remaining_minutes, 0)
        self.assertLessEqual(abs(result.remaining_minutes - (first_remaining - 1)), 8)


if __name__ == "__main__":
    unittest.main()
