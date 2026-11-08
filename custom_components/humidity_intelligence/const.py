"""Constants for the Humidity Intelligence integration."""

from __future__ import annotations

DOMAIN: str = "humidity_intelligence"

# Version of the config entry data schema. Increment when migrating structure.
CONF_VERSION: int = 1

# Default time gate values
DEFAULT_TIME_START = "08:00"
DEFAULT_TIME_END = "22:00"
ENGINE_INTERVAL_MINUTES_DEFAULT = 5
ENGINE_INTERVAL_MIN = 1
ENGINE_INTERVAL_MAX = 30
ENGINE_INTERVAL_STEP = 1
CONF_AUTO_REFRESH_UI_ON_STARTUP = "auto_refresh_ui_on_startup"
DEFAULT_AUTO_REFRESH_UI_ON_STARTUP = True
CONF_ALERT_HANDLING_ENABLED = "alert_handling_enabled"
DEFAULT_ALERT_HANDLING_ENABLED = True
CONF_SHOW_TEMPERATURE_CHIPS = "show_temperature_chips"
DEFAULT_SHOW_TEMPERATURE_CHIPS = False
CONF_SHOW_OUTPUT_ENTITY_DETAILS = "show_output_entity_details"
DEFAULT_SHOW_OUTPUT_ENTITY_DETAILS = False
CONF_LEVEL_LABELS = "level_labels"
CONF_LEVEL1_LABEL = "level1_label"
CONF_LEVEL2_LABEL = "level2_label"
LEVEL_LABEL_FALLBACKS = {
    "level1": "Level 1",
    "level2": "Level 2",
}
LEVEL_LABEL_MAX_LENGTH = 32
STARTUP_UI_REFRESH_DELAY_SECONDS = 5

# Supported sensor types for telemetry input
SENSOR_TYPES = [
    {"value": "humidity", "label": "Humidity"},
    {"value": "temperature", "label": "Temperature"},
    {"value": "co2", "label": "CO2"},
    {"value": "voc", "label": "VOC"},
    {"value": "iaq", "label": "IAQ"},
    {"value": "pm25", "label": "PM2.5"},
    {"value": "co", "label": "CO"},
]

LEVELS = [
    {"value": "level1", "label": LEVEL_LABEL_FALLBACKS["level1"]},
    {"value": "level2", "label": LEVEL_LABEL_FALLBACKS["level2"]},
]

COMMON_ROOMS = [
    "Bathroom",
    "Bedroom",
    "Cloakroom",
    "Dining Room",
    "Downstairs Toilet",
    "Ensuite",
    "Garage",
    "Hallway",
    "Kitchen",
    "Landing",
    "Living Room",
    "Lounge",
    "Master Bedroom",
    "Office",
    "Shower Room",
    "Spare Room",
    "Study",
    "Toilet",
    "Utility",
    "Wet Room",
]

OUTSIDE_WINDOW_ACTIONS = [
    {"value": "no_action", "label": "No action"},
    {"value": "pause", "label": "Pause automations"},
    {"value": "safe_state", "label": "Force safe state"},
]

TARGET_PROFILE_OPTIONS = [
    {"value": "auto", "label": "Auto (seasonal)"},
    {"value": "spring", "label": "Spring"},
    {"value": "summer", "label": "Summer"},
    {"value": "autumn", "label": "Autumn"},
    {"value": "winter", "label": "Winter"},
    {"value": "custom", "label": "Custom"},
]
TARGET_CUSTOM_LOW_MIN = 30
TARGET_CUSTOM_LOW_MAX = 65
TARGET_CUSTOM_HIGH_MIN = 35
TARGET_CUSTOM_HIGH_MAX = 75
TARGET_CUSTOM_STEP = 0.5

TEMPERATURE_COMFORT_PROFILE_OPTIONS = [
    {"value": "auto", "label": "Auto (seasonal)"},
    {"value": "custom", "label": "Custom"},
]
TEMPERATURE_COMFORT_CUSTOM_LOW_MIN = 16
TEMPERATURE_COMFORT_CUSTOM_LOW_MAX = 24
TEMPERATURE_COMFORT_CUSTOM_HIGH_MIN = 17
TEMPERATURE_COMFORT_CUSTOM_HIGH_MAX = 26
TEMPERATURE_COMFORT_CUSTOM_STEP = 0.5
DEFAULT_TEMPERATURE_COMFORT_MODE = "auto"
DEFAULT_TEMPERATURE_COMFORT_CUSTOM_LOW = 19.5
DEFAULT_TEMPERATURE_COMFORT_CUSTOM_HIGH = 21.0

# Optional frontend dependencies used by the dashboards
DEPENDENCIES = [
    {
        "name": "card-mod",
        "url": "https://github.com/thomasloven/lovelace-card-mod",
        "resource": "card-mod.js",
        "domain": "card_mod",
    },
    {
        "name": "button-card",
        "url": "https://github.com/custom-cards/button-card",
        "resource": "button-card.js",
        "domain": "button_card",
    },
    {
        "name": "mod-card",
        "url": "https://github.com/thomasloven/lovelace-card-mod",
        "resource": "mod-card.js",
        "domain": "mod_card",
    },
    {
        "name": "apexcharts-card",
        "url": "https://github.com/RomRider/apexcharts-card",
        "resource": "apexcharts-card.js",
        "domain": "apexcharts_card",
    },
]

# Slope modes
SLOPE_MODE_CALCULATED = "hi_calculates"
SLOPE_MODE_PROVIDED = "user_provided"
SLOPE_MODE_NONE = "skip"

# Trigger definitions for zone automations
TRIGGER_DEFS = {
    "humidity_high": {
        "label": "Humidity above house average",
        "min": 2,
        "max": 20,
        "default": 5,
        "unit": "%",
    },
    "condensation_risk": {"label": "Condensation risk", "min": 2, "max": 6, "default": 4, "unit": "degC"},
    "mould_risk": {"label": "Mould risk", "min": 1, "max": 3, "default": 2, "unit": "level"},
    "air_quality_bad": {"label": "Air quality bad", "min": 50, "max": 90, "default": 70, "unit": "IAQ"},
}

# Zone output tuning
ZONE_OUTPUT_LEVEL_MIN = 30
ZONE_OUTPUT_LEVEL_MAX = 100
ZONE_OUTPUT_LEVEL_STEP = 5
ZONE_OUTPUT_LEVEL_DEFAULT = 66
ZONE_OUTPUT_LEVEL_BOOST_DEFAULT = 100
FAN_OUTPUT_LEVEL_AUTO = "auto"
FAN_OUTPUT_LEVEL_STEPS = [33, 66, 100]

# Trigger definitions for AQ automations
AQ_TRIGGER_DEFS = {
    "iaq_bad": {"label": "IAQ bad", "min": 60, "max": 90, "default": 75, "unit": "IAQ"},
    "pm25_high": {"label": "PM2.5 high", "min": 12, "max": 65, "default": 35, "unit": "ug/m3"},
    "voc_bad": {"label": "VOC bad", "min": 200, "max": 1000, "default": 600, "unit": "ppb"},
    "co2_high": {"label": "CO2 high", "min": 800, "max": 2000, "default": 1200, "unit": "ppm"},
    "co_warning": {"label": "CO warning", "min": 5, "max": 50, "default": 15, "unit": "ppm"},
}

# Alert trigger types
ALERT_TRIGGER_DEFS = {
    "humidity_danger": {"label": "Humidity Danger"},
    "condensation_risk": {"label": "Condensation Risk"},
    "mould_risk": {"label": "Mould Risk"},
    "condensation_danger": {"label": "Condensation Danger"},
    "mould_danger": {"label": "Mould Danger"},
    "co_emergency": {"label": "CO Emergency"},
}

# Alert trigger types that support room-scoped evaluation.
ROOM_SCOPED_ALERT_TRIGGERS = (
    "humidity_danger",
    "condensation_danger",
    "condensation_risk",
    "mould_danger",
    "mould_risk",
)

# Safety guardrails for static alert thresholds.
# Humidity Danger follows the active target profile high-risk threshold at runtime.
ALERT_THRESHOLD_BOUNDS = {
    "co_emergency": {"min": 10, "max": 100, "default": 15, "unit": "ppm"},
}

ALERT_FLASH_MODES = [
    {"value": "red", "label": "Red flash"},
    {"value": "white", "label": "White flash"},
]

# Humidifier band adjust
HUMIDIFIER_BAND_MIN = -3
HUMIDIFIER_BAND_MAX = 3
HUMIDIFIER_BAND_STEP = 0.5
HUMIDIFIER_RECOVERY_IN_BAND_DEFAULT = 3
HUMIDIFIER_RECONCILE_CONFIRM_SECONDS = 15
HUMIDIFIER_RECONCILE_RETRY_DELAYS_SECONDS = (30, 120)
HUMIDIFIER_RECONCILE_MAX_ATTEMPTS = 3
HUMIDIFIER_RECONCILE_HISTORY_LIMIT = 8

# AQ outputs tuning
AQ_DURATION_MIN = 5
AQ_DURATION_MAX = 180
AQ_DURATION_STEP = 5
AQ_OUTPUT_LEVEL_MIN = 30
AQ_OUTPUT_LEVEL_MAX = 100
AQ_OUTPUT_LEVEL_STEP = 5

# UI helper behavior
UI_DROPDOWN_AUTO_CLOSE_SECONDS = 120
STARTUP_SENSOR_RECHECK_SECONDS = 60

# Alert durations
ALERT_DURATION_MIN = 5
ALERT_DURATION_MAX = 120
ALERT_DURATION_STEP = 5

# Max number of alert/emergency automations
MAX_ALERTS = 5
