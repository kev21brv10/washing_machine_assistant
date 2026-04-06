from __future__ import annotations

from datetime import timedelta

DOMAIN = "washing_machine_assistant"

PLATFORMS: list[str] = ["sensor", "binary_sensor", "button"]

CONF_NAME = "name"
CONF_POWER_SENSOR = "power_sensor"
CONF_VIBRATION_SENSOR = "vibration_sensor"
CONF_DOOR_SENSOR = "door_sensor"
CONF_START_POWER_W = "start_power_w"
CONF_STOP_POWER_W = "stop_power_w"
CONF_HIGH_POWER_W = "high_power_w"
CONF_FINISH_GRACE_MINUTES = "finish_grace_minutes"
CONF_RESET_FINISHED_MINUTES = "reset_finished_minutes"
CONF_UPDATE_INTERVAL_SECONDS = "update_interval_seconds"

DEFAULT_NAME = "Machine a laver"
DEFAULT_START_POWER_W = 8.0
DEFAULT_STOP_POWER_W = 3.0
DEFAULT_HIGH_POWER_W = 1200.0
DEFAULT_FINISH_GRACE_MINUTES = 5
DEFAULT_RESET_FINISHED_MINUTES = 180
DEFAULT_UPDATE_INTERVAL_SECONDS = 30

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SECONDS)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_UNAVAILABLE = "unavailable"

PHASE_IDLE = "idle"
PHASE_STARTING = "starting"
PHASE_HEATING = "heating"
PHASE_WASHING = "washing"
PHASE_RINSING = "rinsing"
PHASE_SPINNING = "spinning"
PHASE_COOLDOWN = "cooldown"
PHASE_FINISHED = "finished"
PHASE_UNKNOWN = "unknown"

PROGRAM_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

PROGRAM_SOURCE_BUILTIN = "builtin"
PROGRAM_SOURCE_LEARNED = "learned"

SERVICE_RENAME_LEARNED_MODE = "rename_learned_mode"
SERVICE_DELETE_LEARNED_MODE = "delete_learned_mode"
SERVICE_MERGE_LEARNED_MODES = "merge_learned_modes"
SERVICE_CONFIRM_LEARNED_MODE = "confirm_learned_mode"
