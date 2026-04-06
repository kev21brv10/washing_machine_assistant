from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any

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
    PROGRAM_UNKNOWN,
    STATUS_FINISHED,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNAVAILABLE,
)


@dataclass(frozen=True)
class ProgramProfile:
    slug: str
    label: str
    min_duration_min: int
    typical_duration_min: int
    max_duration_min: int
    source: str = "builtin"
    sample_count: int = 0
    peak_power_w: float | None = None
    uses_heating: bool | None = None
    avg_power_w: float | None = None
    high_power_ratio: float | None = None
    spin_ratio: float | None = None
    signature: list[int] | None = None


@dataclass(frozen=True)
class CycleFeatures:
    duration_min: int
    peak_power_w: float | None
    uses_heating: bool | None
    avg_power_w: float | None
    high_power_ratio: float | None
    spin_ratio: float | None
    signature: list[int] | None = None
    start_power_w: float | None = None
    stop_power_w: float | None = None


@dataclass(frozen=True)
class MachineTelemetry:
    timestamp: datetime
    power_w: float | None
    vibration_on: bool = False
    door_open: bool | None = None


@dataclass(frozen=True)
class InferenceResult:
    available: bool
    status: str
    phase: str
    probable_program: str
    program_label: str
    program_source: str
    confidence: str
    match_score: int | None
    power_w: float | None
    remaining_minutes: int | None
    finish_time: datetime | None
    cycle_started_at: datetime | None
    last_activity_at: datetime | None
    elapsed_minutes: int | None
    observed_peak_power_w: float
    diagnostics: dict[str, Any]

    @property
    def is_running(self) -> bool:
        return self.status == STATUS_RUNNING

    @property
    def is_finished(self) -> bool:
        return self.status == STATUS_FINISHED


PROGRAM_PROFILES: tuple[ProgramProfile, ...] = (
    ProgramProfile("rinse_spin", "Rincage + essorage", 15, 25, 45),
    ProgramProfile("quick", "Rapide", 20, 35, 50),
    ProgramProfile("synthetics", "Synthetiques", 50, 75, 100),
    ProgramProfile("mixed", "Mixte", 80, 110, 140),
    ProgramProfile("cotton", "Coton", 110, 150, 190),
    ProgramProfile("eco", "Eco", 150, 210, 260),
)

PHASE_PROGRESS_HINTS: dict[str, float] = {
    PHASE_STARTING: 0.05,
    PHASE_HEATING: 0.18,
    PHASE_WASHING: 0.38,
    PHASE_RINSING: 0.72,
    PHASE_SPINNING: 0.90,
    PHASE_COOLDOWN: 0.97,
}


class WashingMachineInferenceEngine:
    """Infer washing machine phase, probable program and finish time."""

    def __init__(
        self,
        *,
        start_power_w: float,
        stop_power_w: float,
        high_power_w: float,
        finish_grace_minutes: int,
        reset_finished_minutes: int,
    ) -> None:
        self._start_power_w = start_power_w
        self._stop_power_w = stop_power_w
        self._high_power_w = high_power_w
        self._finish_grace = timedelta(minutes=finish_grace_minutes)
        self._reset_finished_after = timedelta(minutes=reset_finished_minutes)
        self._start_confirmation = timedelta(minutes=1)
        self._power_window: deque[float] = deque(maxlen=16)
        self._learned_profiles: tuple[ProgramProfile, ...] = ()
        self._reset_runtime()

    def set_learned_profiles(self, profiles: list[ProgramProfile]) -> None:
        self._learned_profiles = tuple(profiles)

    def restore_completed_cycle(self, result: InferenceResult | None, completed_at: datetime | None) -> None:
        self._completed_result = result
        self._completed_at = completed_at

    def restore_runtime_state(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        cycle_started_at = payload.get("cycle_started_at")
        if cycle_started_at is None:
            return
        self._completed_result = None
        self._completed_at = None
        self._cycle_started_at = cycle_started_at
        self._last_activity_at = payload.get("last_activity_at")
        self._inactive_since = payload.get("inactive_since")
        self._pending_start_since = None
        self._observed_peak_power_w = float(payload.get("observed_peak_power_w", 0.0) or 0.0)
        self._high_power_samples = int(payload.get("high_power_samples", 0) or 0)
        self._spin_like_samples = int(payload.get("spin_like_samples", 0) or 0)
        self._power_window = deque((payload.get("power_window") or [])[-16:], maxlen=16)
        self._cycle_power_samples = list(payload.get("cycle_power_samples") or [])
        self._cycle_vibration_samples = [bool(value) for value in (payload.get("cycle_vibration_samples") or [])]
        self._locked_profile_slug = payload.get("locked_profile_slug")
        self._locked_profile_score = payload.get("locked_profile_score")
        self._best_candidate_slug = payload.get("best_candidate_slug")
        self._best_candidate_score = payload.get("best_candidate_score")
        self._locked_phase = payload.get("locked_phase")
        self._pending_phase = payload.get("pending_phase")
        self._pending_phase_count = int(payload.get("pending_phase_count", 0) or 0)
        self._estimated_total_minutes = payload.get("estimated_total_minutes")

    def set_runtime_thresholds(
        self,
        *,
        start_power_w: float | None = None,
        stop_power_w: float | None = None,
        high_power_w: float | None = None,
    ) -> None:
        if start_power_w is not None:
            self._start_power_w = start_power_w
        if stop_power_w is not None:
            self._stop_power_w = stop_power_w
        if high_power_w is not None:
            self._high_power_w = high_power_w

    def export_runtime_state(self) -> dict[str, Any] | None:
        if self._cycle_started_at is None:
            return None
        return {
            "cycle_started_at": self._cycle_started_at,
            "last_activity_at": self._last_activity_at,
            "inactive_since": self._inactive_since,
            "observed_peak_power_w": self._observed_peak_power_w,
            "high_power_samples": self._high_power_samples,
            "spin_like_samples": self._spin_like_samples,
            "power_window": list(self._power_window),
            "cycle_power_samples": self._cycle_power_samples[-480:],
            "cycle_vibration_samples": self._cycle_vibration_samples[-480:],
            "locked_profile_slug": self._locked_profile_slug,
            "locked_profile_score": self._locked_profile_score,
            "best_candidate_slug": self._best_candidate_slug,
            "best_candidate_score": self._best_candidate_score,
            "locked_phase": self._locked_phase,
            "pending_phase": self._pending_phase,
            "pending_phase_count": self._pending_phase_count,
            "estimated_total_minutes": self._estimated_total_minutes,
        }

    def _reset_runtime(self) -> None:
        self._cycle_started_at: datetime | None = None
        self._last_activity_at: datetime | None = None
        self._inactive_since: datetime | None = None
        self._pending_start_since: datetime | None = None
        self._observed_peak_power_w = 0.0
        self._high_power_samples = 0
        self._spin_like_samples = 0
        self._power_window.clear()
        self._cycle_power_samples: list[float] = []
        self._cycle_vibration_samples: list[bool] = []
        self._completed_result: InferenceResult | None = None
        self._completed_at: datetime | None = None
        self._locked_profile_slug: str | None = None
        self._locked_profile_score: float | None = None
        self._best_candidate_slug: str | None = None
        self._best_candidate_score: float | None = None
        self._locked_phase: str | None = None
        self._pending_phase: str | None = None
        self._pending_phase_count = 0
        self._estimated_total_minutes: int | None = None

    def update(self, telemetry: MachineTelemetry) -> InferenceResult:
        now = telemetry.timestamp
        power_w = telemetry.power_w

        if power_w is None:
            return InferenceResult(
                available=False,
                status=STATUS_UNAVAILABLE,
                phase=PHASE_UNKNOWN,
                probable_program=PROGRAM_UNKNOWN,
                program_label="Inconnu",
                program_source="builtin",
                confidence=CONFIDENCE_LOW,
                match_score=None,
                power_w=None,
                remaining_minutes=None,
                finish_time=None,
                cycle_started_at=self._cycle_started_at,
                last_activity_at=self._last_activity_at,
                elapsed_minutes=self._elapsed_minutes(now),
                observed_peak_power_w=self._observed_peak_power_w,
                diagnostics={"reason": "power_sensor_unavailable"},
            )

        is_start_candidate = power_w >= self._start_power_w or telemetry.vibration_on
        is_active = power_w >= self._stop_power_w or telemetry.vibration_on

        if self._completed_result is not None:
            if telemetry.door_open:
                self._completed_result = None
                self._completed_at = None
            elif self._completed_at and now - self._completed_at >= self._reset_finished_after:
                self._completed_result = None
                self._completed_at = None
            elif is_start_candidate:
                self._completed_result = None
                self._completed_at = None
            else:
                return self._completed_result

        if self._cycle_started_at is None:
            if is_start_candidate:
                if self._pending_start_since is None:
                    self._pending_start_since = now
                elif now - self._pending_start_since >= self._start_confirmation:
                    self._start_cycle(now, power_w)
            else:
                self._pending_start_since = None
            if self._cycle_started_at is None:
                return self._build_idle_result(power_w)

        self._power_window.append(power_w)
        self._cycle_power_samples.append(power_w)
        self._cycle_vibration_samples.append(telemetry.vibration_on)

        if is_active:
            self._last_activity_at = now
            self._inactive_since = None
            self._observed_peak_power_w = max(self._observed_peak_power_w, power_w)
            if power_w >= self._high_power_w:
                self._high_power_samples += 1
            if telemetry.vibration_on and power_w >= max(self._stop_power_w * 3, 20):
                self._spin_like_samples += 1
        else:
            if self._inactive_since is None:
                self._inactive_since = now
            elif now - self._inactive_since >= self._finish_grace:
                return self._finish_cycle(now, power_w)

        phase = self._infer_phase(now, power_w, telemetry.vibration_on)
        program, profile, confidence, match_score = self._infer_program(now, phase)
        remaining_minutes, finish_time = self._estimate_remaining(now, phase, profile)

        return InferenceResult(
            available=True,
            status=STATUS_RUNNING,
            phase=phase,
            probable_program=program,
            program_label=profile.label,
            program_source=profile.source,
            confidence=confidence,
            match_score=match_score,
            power_w=power_w,
            remaining_minutes=remaining_minutes,
            finish_time=finish_time,
            cycle_started_at=self._cycle_started_at,
            last_activity_at=self._last_activity_at,
            elapsed_minutes=self._elapsed_minutes(now),
            observed_peak_power_w=self._observed_peak_power_w,
            diagnostics={
                **self._match_diagnostics(),
                "high_power_samples": self._high_power_samples,
                "spin_like_samples": self._spin_like_samples,
                "pending_finish": self._inactive_since is not None,
                "cycle_signature": self._build_cycle_signature(self._cycle_power_samples, self._cycle_vibration_samples),
            },
        )

    def _start_cycle(self, now: datetime, power_w: float) -> None:
        self._cycle_started_at = self._pending_start_since or now
        self._last_activity_at = now
        self._inactive_since = None
        self._observed_peak_power_w = power_w
        self._high_power_samples = 1 if power_w >= self._high_power_w else 0
        self._spin_like_samples = 0
        self._power_window.clear()
        self._power_window.append(power_w)
        self._cycle_power_samples = []
        self._cycle_vibration_samples = []
        self._pending_start_since = None
        self._locked_profile_slug = None
        self._locked_profile_score = None
        self._best_candidate_slug = None
        self._best_candidate_score = None
        self._locked_phase = PHASE_STARTING
        self._pending_phase = None
        self._pending_phase_count = 0
        self._estimated_total_minutes = None

    def _finish_cycle(self, now: datetime, power_w: float) -> InferenceResult:
        phase = PHASE_FINISHED
        program, profile, confidence, match_score = self._infer_program(now, phase)
        finished_at = self._last_activity_at or now
        cycle_signature = self._build_cycle_signature(self._cycle_power_samples, self._cycle_vibration_samples)
        result = InferenceResult(
            available=True,
            status=STATUS_FINISHED,
            phase=phase,
            probable_program=program,
            program_label=profile.label,
            program_source=profile.source,
            confidence=confidence,
            match_score=match_score,
            power_w=power_w,
            remaining_minutes=0,
            finish_time=finished_at,
            cycle_started_at=self._cycle_started_at,
            last_activity_at=finished_at,
            elapsed_minutes=self._elapsed_minutes(finished_at),
            observed_peak_power_w=self._observed_peak_power_w,
            diagnostics={
                **self._match_diagnostics(),
                "high_power_samples": self._high_power_samples,
                "spin_like_samples": self._spin_like_samples,
                "cycle_signature": cycle_signature,
            },
        )
        self._completed_result = result
        self._completed_at = now
        self._cycle_started_at = None
        self._last_activity_at = None
        self._inactive_since = None
        self._pending_start_since = None
        self._observed_peak_power_w = 0.0
        self._high_power_samples = 0
        self._spin_like_samples = 0
        self._power_window.clear()
        self._best_candidate_slug = None
        self._best_candidate_score = None
        self._locked_phase = None
        self._pending_phase = None
        self._pending_phase_count = 0
        return result

    def _build_idle_result(self, power_w: float) -> InferenceResult:
        return InferenceResult(
            available=True,
            status=STATUS_IDLE,
            phase=PHASE_IDLE,
            probable_program=PROGRAM_UNKNOWN,
            program_label="Inconnu",
            program_source="builtin",
            confidence=CONFIDENCE_LOW,
            match_score=None,
            power_w=power_w,
            remaining_minutes=None,
            finish_time=None,
            cycle_started_at=None,
            last_activity_at=None,
            elapsed_minutes=None,
            observed_peak_power_w=0.0,
            diagnostics={},
        )

    def _elapsed_minutes(self, now: datetime) -> int | None:
        if self._cycle_started_at is None:
            return None
        return max(0, int((now - self._cycle_started_at).total_seconds() // 60))

    def _infer_phase(self, now: datetime, power_w: float, vibration_on: bool) -> str:
        elapsed = self._elapsed_minutes(now)
        wash_threshold = max(self._start_power_w * 8, 60)
        rinse_threshold = max(self._start_power_w * 2, 15)
        progress = self._cycle_progress(elapsed)
        late_cycle = progress is not None and progress >= 0.55
        final_cycle = progress is not None and progress >= 0.82
        if late_cycle:
            wash_threshold = max(wash_threshold, 110.0)
            rinse_threshold = max(rinse_threshold, 18.0)
        if elapsed is not None and elapsed < 5 and power_w < self._high_power_w:
            candidate_phase = PHASE_STARTING
        elif power_w >= self._high_power_w:
            candidate_phase = PHASE_HEATING
        elif self._looks_like_spinning(elapsed, power_w, vibration_on, wash_threshold, rinse_threshold):
            candidate_phase = PHASE_SPINNING
        else:
            if power_w >= wash_threshold:
                candidate_phase = PHASE_WASHING
            elif power_w >= rinse_threshold:
                candidate_phase = PHASE_RINSING
            elif final_cycle and power_w < max(rinse_threshold, 18.0):
                candidate_phase = PHASE_COOLDOWN
            elif late_cycle and power_w >= max(self._stop_power_w, 6.0):
                candidate_phase = PHASE_RINSING
            else:
                candidate_phase = PHASE_COOLDOWN
        return self._stabilize_phase(candidate_phase)

    def _cycle_progress(self, elapsed: int | None) -> float | None:
        if elapsed is None or elapsed <= 0:
            return None
        estimated_total = self._estimated_total_minutes or self._estimate_total_duration(elapsed, PHASE_WASHING)
        return elapsed / max(estimated_total, 1)

    def _looks_like_spinning(
        self,
        elapsed: int | None,
        power_w: float,
        vibration_on: bool,
        wash_threshold: float,
        rinse_threshold: float,
    ) -> bool:
        if vibration_on and power_w >= max(self._stop_power_w * 3, 20):
            return True
        if elapsed is None or elapsed < 20 or self._high_power_samples == 0:
            return False

        recent_samples = list(self._power_window)[-6:]
        if len(recent_samples) < 4:
            return False

        estimated_total = self._estimated_total_minutes or self._estimate_total_duration(elapsed, PHASE_WASHING)
        progress = elapsed / max(estimated_total, 1)
        if progress < 0.72:
            return False

        recent_avg = sum(recent_samples) / len(recent_samples)
        recent_max = max(recent_samples)
        recent_min = min(recent_samples)
        spin_floor = max(wash_threshold * 1.35, 90.0)
        spin_cap = max(self._high_power_w * 0.55, spin_floor)

        if recent_avg < spin_floor or recent_max > spin_cap:
            return False
        if recent_min <= self._stop_power_w:
            return False
        if power_w < rinse_threshold * 1.5:
            return False
        return True

    def _stabilize_phase(self, candidate_phase: str) -> str:
        immediate_phases = {PHASE_STARTING, PHASE_HEATING, PHASE_FINISHED, PHASE_IDLE, PHASE_UNKNOWN}
        if self._locked_phase is None:
            self._locked_phase = candidate_phase
            self._pending_phase = None
            self._pending_phase_count = 0
            return candidate_phase

        if candidate_phase == self._locked_phase:
            self._pending_phase = None
            self._pending_phase_count = 0
            return candidate_phase

        if candidate_phase in immediate_phases or self._locked_phase in immediate_phases:
            self._locked_phase = candidate_phase
            self._pending_phase = None
            self._pending_phase_count = 0
            return candidate_phase

        confirmation_needed = 2
        if {self._locked_phase, candidate_phase} == {PHASE_WASHING, PHASE_RINSING}:
            confirmation_needed = 3
        elif candidate_phase == PHASE_COOLDOWN and self._locked_phase in {PHASE_WASHING, PHASE_RINSING}:
            confirmation_needed = 3

        if self._pending_phase == candidate_phase:
            self._pending_phase_count += 1
        else:
            self._pending_phase = candidate_phase
            self._pending_phase_count = 1

        if self._pending_phase_count >= confirmation_needed:
            self._locked_phase = candidate_phase
            self._pending_phase = None
            self._pending_phase_count = 0

        return self._locked_phase

    def _infer_program(self, now: datetime, phase: str) -> tuple[str, ProgramProfile, str, int | None]:
        if phase == PHASE_FINISHED and self._completed_result is not None:
            return (
                self._completed_result.probable_program,
                ProgramProfile(
                    slug=self._completed_result.probable_program,
                    label=self._completed_result.program_label,
                    min_duration_min=self._completed_result.elapsed_minutes or 0,
                    typical_duration_min=self._completed_result.elapsed_minutes or 0,
                    max_duration_min=self._completed_result.elapsed_minutes or 0,
                    source=self._completed_result.program_source,
                ),
                self._completed_result.confidence,
                self._completed_result.match_score,
            )

        elapsed = self._elapsed_minutes(now)
        if elapsed is None or elapsed < 10:
            return PROGRAM_UNKNOWN, self._unknown_profile(), CONFIDENCE_LOW, None

        estimated_total = self._estimate_total_duration(elapsed, phase)
        best_profile: ProgramProfile | None = None
        best_score: float | None = None
        scores_by_slug: dict[str, float] = {}
        current_signature = self._build_cycle_signature(self._cycle_power_samples, self._cycle_vibration_samples)

        candidate_profiles = self._learned_profiles or PROGRAM_PROFILES
        for profile in candidate_profiles:
            score = abs(profile.typical_duration_min - estimated_total)
            if estimated_total < profile.min_duration_min:
                score += (profile.min_duration_min - estimated_total) * 1.5
            if estimated_total > profile.max_duration_min:
                score += (estimated_total - profile.max_duration_min) * 1.5
            if profile.slug == "rinse_spin" and self._high_power_samples > 0:
                score += 40
            if profile.slug in {"eco", "cotton"} and self._high_power_samples == 0:
                score += 15
            if profile.slug == "quick" and estimated_total > 60:
                score += 25
            if profile.peak_power_w is not None and self._observed_peak_power_w > 0:
                score += min(abs(profile.peak_power_w - self._observed_peak_power_w) / 80, 20)
            if profile.uses_heating is not None:
                has_heating = self._high_power_samples > 0
                if profile.uses_heating != has_heating:
                    score += 20
            if profile.avg_power_w is not None and current_signature["avg_power_w"] is not None:
                score += min(abs(profile.avg_power_w - current_signature["avg_power_w"]) / 25, 20)
            if profile.high_power_ratio is not None and current_signature["high_power_ratio"] is not None:
                score += abs(profile.high_power_ratio - current_signature["high_power_ratio"]) * 35
            if profile.spin_ratio is not None and current_signature["spin_ratio"] is not None:
                score += abs(profile.spin_ratio - current_signature["spin_ratio"]) * 25
            signature_score = self._signature_distance(profile.signature, current_signature["signature"])
            if signature_score is not None:
                score += signature_score * 0.45
            scores_by_slug[profile.slug] = score
            if best_score is None or score < best_score:
                best_score = score
                best_profile = profile

        if best_profile is None:
            return PROGRAM_UNKNOWN, self._unknown_profile(), CONFIDENCE_LOW, None

        best_profile, best_score = self._stabilize_program_choice(
            elapsed_minutes=elapsed,
            candidate_profile=best_profile,
            candidate_score=best_score,
            scores_by_slug=scores_by_slug,
        )
        self._best_candidate_slug = best_profile.slug
        self._best_candidate_score = best_score
        match_score = self._score_to_similarity(best_score)
        if self._learned_profiles and best_profile.source == "learned" and (match_score or 0) < 60:
            return PROGRAM_UNKNOWN, self._unknown_profile(), CONFIDENCE_LOW, match_score
        confidence = self._confidence_for_program(elapsed, match_score)
        return best_profile.slug, best_profile, confidence, match_score

    def _stabilize_program_choice(
        self,
        *,
        elapsed_minutes: int,
        candidate_profile: ProgramProfile,
        candidate_score: float,
        scores_by_slug: dict[str, float],
    ) -> tuple[ProgramProfile, float]:
        if self._locked_profile_slug is None or elapsed_minutes < 20:
            self._locked_profile_slug = candidate_profile.slug
            self._locked_profile_score = candidate_score
            return candidate_profile, candidate_score

        if self._locked_profile_slug == candidate_profile.slug:
            self._locked_profile_score = candidate_score
            return candidate_profile, candidate_score

        locked_profile = next(
            (
                profile
                for profile in (*self._learned_profiles, *PROGRAM_PROFILES)
                if profile.slug == self._locked_profile_slug
            ),
            None,
        )
        locked_score = scores_by_slug.get(self._locked_profile_slug, self._locked_profile_score or candidate_score)
        if locked_profile is None:
            self._locked_profile_slug = candidate_profile.slug
            self._locked_profile_score = candidate_score
            return candidate_profile, candidate_score

        switch_margin = 12.0
        if candidate_profile.source == "learned" and locked_profile.source != "learned":
            switch_margin = 6.0
        elif candidate_profile.source == locked_profile.source == "learned":
            switch_margin = 14.0
            if elapsed_minutes >= 35:
                switch_margin = 18.0

        locked_match = self._score_to_similarity(locked_score)
        if locked_match is not None and locked_match < 45:
            switch_margin = min(switch_margin, 5.0)
        elif locked_match is not None and locked_match >= 70 and candidate_profile.source == locked_profile.source == "learned":
            switch_margin += 4.0

        if candidate_score + switch_margin < locked_score:
            self._locked_profile_slug = candidate_profile.slug
            self._locked_profile_score = candidate_score
            self._estimated_total_minutes = None
            return candidate_profile, candidate_score

        self._locked_profile_score = locked_score
        return locked_profile, locked_score

    def _estimate_total_duration(self, elapsed_minutes: int, phase: str) -> int:
        progress = PHASE_PROGRESS_HINTS.get(phase)
        if progress is None or progress <= 0:
            return elapsed_minutes
        estimate = max(elapsed_minutes, int(round(elapsed_minutes / progress)))
        return min(estimate, 320)

    def _confidence_for_program(self, elapsed_minutes: int, match_score: int) -> str:
        if elapsed_minutes < 20:
            return CONFIDENCE_LOW
        if match_score >= 82 and elapsed_minutes >= 45:
            return CONFIDENCE_HIGH
        if match_score >= 60 and elapsed_minutes >= 25:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW

    def _estimate_remaining(
        self,
        now: datetime,
        phase: str,
        profile: ProgramProfile,
    ) -> tuple[int | None, datetime | None]:
        elapsed = self._elapsed_minutes(now)
        if elapsed is None or profile.slug == PROGRAM_UNKNOWN:
            return None, None

        progress_based_total = self._estimate_total_duration(elapsed, phase)
        predicted_total = max(profile.min_duration_min, min(progress_based_total, profile.max_duration_min))
        predicted_total = self._smooth_total_duration(predicted_total, elapsed)
        remaining = max(0, predicted_total - elapsed)
        finish_time = now + timedelta(minutes=remaining)
        return remaining, finish_time

    def _smooth_total_duration(self, target_total: int, elapsed_minutes: int) -> int:
        target_total = max(elapsed_minutes, target_total)
        if self._estimated_total_minutes is None:
            self._estimated_total_minutes = target_total
            return target_total

        current = self._estimated_total_minutes
        if target_total > current:
            smoothed = int(round((current * 0.8) + (target_total * 0.2)))
        else:
            smoothed = int(round((current * 0.65) + (target_total * 0.35)))

        smoothed = max(elapsed_minutes, smoothed)
        self._estimated_total_minutes = smoothed
        return smoothed

    def _build_cycle_signature(self, power_samples: list[float], vibration_samples: list[bool]) -> dict[str, Any]:
        trimmed_power_samples, trimmed_vibration_samples = self._trim_idle_tail(power_samples, vibration_samples)
        if not trimmed_power_samples:
            return {
                "avg_power_w": None,
                "high_power_ratio": None,
                "spin_ratio": None,
                "signature": [],
            }
        active_samples = [sample for sample in trimmed_power_samples if sample >= self._start_power_w]
        peak_power = max(trimmed_power_samples) if trimmed_power_samples else 0.0
        signature = self._compress_signature(trimmed_power_samples, peak_power)
        return {
            "avg_power_w": round(sum(active_samples) / len(active_samples), 1) if active_samples else 0.0,
            "high_power_ratio": round(
                sum(1 for sample in trimmed_power_samples if sample >= self._high_power_w) / len(trimmed_power_samples),
                3,
            ),
            "spin_ratio": round(
                sum(
                    1
                    for sample, vibration in zip(trimmed_power_samples, trimmed_vibration_samples)
                    if vibration and sample >= self._start_power_w
                )
                / len(trimmed_power_samples),
                3,
            ),
            "signature": signature,
            "start_power_w": round(max(4.0, min(40.0, max(8.0, min(active_samples) * 0.7))), 1) if active_samples else None,
            "stop_power_w": round(max(1.0, min(15.0, min(trimmed_power_samples) + 1.0)), 1) if trimmed_power_samples else None,
        }

    def build_cycle_signature(self, power_samples: list[float], vibration_samples: list[bool]) -> dict[str, Any]:
        return self._build_cycle_signature(power_samples, vibration_samples)

    def _trim_idle_tail(
        self,
        power_samples: list[float],
        vibration_samples: list[bool],
    ) -> tuple[list[float], list[bool]]:
        if not power_samples:
            return [], []
        end_index = len(power_samples)
        while end_index > 0:
            sample = power_samples[end_index - 1]
            vibration = vibration_samples[end_index - 1] if end_index - 1 < len(vibration_samples) else False
            if sample >= self._stop_power_w or vibration:
                break
            end_index -= 1
        return power_samples[:end_index], vibration_samples[:end_index]

    @staticmethod
    def _compress_signature(power_samples: list[float], peak_power: float, bucket_count: int = 12) -> list[int]:
        if not power_samples or peak_power <= 0:
            return []
        normalized = [int(round((sample / peak_power) * 100)) for sample in power_samples]
        chunk_size = max(1, len(normalized) // bucket_count)
        compressed: list[int] = []
        index = 0
        while index < len(normalized):
            chunk = normalized[index : index + chunk_size]
            compressed.append(int(round(sum(chunk) / len(chunk))))
            index += chunk_size
        if len(compressed) > bucket_count:
            compressed = compressed[:bucket_count]
        return compressed

    @staticmethod
    def _signature_distance(profile_signature: list[int] | None, current_signature: list[int]) -> float | None:
        if not profile_signature or not current_signature:
            return None
        compare_length = min(len(profile_signature), len(current_signature))
        if compare_length < 4:
            return None
        diffs = [
            abs(profile_signature[index] - current_signature[index])
            for index in range(compare_length)
        ]
        return sum(diffs) / len(diffs)

    @staticmethod
    def _score_to_similarity(score: float | None) -> int | None:
        if score is None:
            return None
        bounded = max(0.0, min(score, 100.0))
        return max(0, min(100, int(round(100 - bounded))))

    @staticmethod
    def _unknown_profile() -> ProgramProfile:
        return ProgramProfile(
            slug=PROGRAM_UNKNOWN,
            label="Inconnu",
            min_duration_min=0,
            typical_duration_min=0,
            max_duration_min=0,
        )

    def _match_diagnostics(self) -> dict[str, Any]:
        return {
            "locked_program_slug": self._locked_profile_slug,
            "locked_program_label": self._profile_label(self._locked_profile_slug),
            "locked_program_score": None
            if self._locked_profile_score is None
            else round(self._locked_profile_score, 1),
            "best_match_slug": self._best_candidate_slug,
            "best_match_label": self._profile_label(self._best_candidate_slug),
            "best_match_score": None
            if self._best_candidate_score is None
            else round(self._best_candidate_score, 1),
        }

    def _profile_label(self, slug: str | None) -> str | None:
        if slug is None:
            return None
        if slug == PROGRAM_UNKNOWN:
            return "Inconnu"
        for profile in (*self._learned_profiles, *PROGRAM_PROFILES):
            if profile.slug == slug:
                return profile.label
        return slug

    def debug_state(self) -> dict[str, Any]:
        return {
            "cycle_started_at": self._cycle_started_at,
            "last_activity_at": self._last_activity_at,
            "inactive_since": self._inactive_since,
            "observed_peak_power_w": self._observed_peak_power_w,
            "high_power_samples": self._high_power_samples,
            "spin_like_samples": self._spin_like_samples,
            "completed": asdict(self._completed_result) if self._completed_result else None,
        }

    @property
    def completed_result(self) -> InferenceResult | None:
        return self._completed_result

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at


def merge_profile(profile: ProgramProfile, features: CycleFeatures) -> ProgramProfile:
    sample_count = max(1, profile.sample_count)
    new_sample_count = sample_count + 1
    observed_min = max(1, features.duration_min - 12)
    observed_max = features.duration_min + 12
    uses_heating_score = (
        ((1 if profile.uses_heating else 0) * sample_count) + (1 if features.uses_heating else 0)
        if profile.uses_heating is not None and features.uses_heating is not None
        else None
    )
    merged_signature = _merge_signatures(profile.signature, features.signature, sample_count)
    return replace(
        profile,
        min_duration_min=_weighted_int(profile.min_duration_min, observed_min, sample_count),
        typical_duration_min=_weighted_int(profile.typical_duration_min, features.duration_min, sample_count),
        max_duration_min=_weighted_int(profile.max_duration_min, observed_max, sample_count),
        sample_count=new_sample_count,
        peak_power_w=_weighted_optional_float(profile.peak_power_w, features.peak_power_w, sample_count),
        uses_heating=None if uses_heating_score is None else (uses_heating_score / new_sample_count) >= 0.5,
        avg_power_w=_weighted_optional_float(profile.avg_power_w, features.avg_power_w, sample_count),
        high_power_ratio=_weighted_optional_float(profile.high_power_ratio, features.high_power_ratio, sample_count),
        spin_ratio=_weighted_optional_float(profile.spin_ratio, features.spin_ratio, sample_count),
        signature=merged_signature,
    )


def _weighted_int(current: int, observed: int, sample_count: int) -> int:
    return int(round(((current * sample_count) + observed) / (sample_count + 1)))


def _weighted_optional_float(current: float | None, observed: float | None, sample_count: int) -> float | None:
    if current is None:
        return observed
    if observed is None:
        return current
    return round(((current * sample_count) + observed) / (sample_count + 1), 3)


def _merge_signatures(
    current: list[int] | None,
    observed: list[int] | None,
    sample_count: int,
) -> list[int] | None:
    if not current:
        return observed
    if not observed:
        return current
    max_len = max(len(current), len(observed))
    merged: list[int] = []
    for index in range(max_len):
        current_value = current[index] if index < len(current) else None
        observed_value = observed[index] if index < len(observed) else None
        if current_value is None:
            merged.append(observed_value)
            continue
        if observed_value is None:
            merged.append(current_value)
            continue
        merged.append(int(round(((current_value * sample_count) + observed_value) / (sample_count + 1))))
    return merged
