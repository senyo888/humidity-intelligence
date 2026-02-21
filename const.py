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
    {"value": "level1", "label": "Level 1 (Downstairs)"},
    {"value": "level2", "label": "Level 2 (Upstairs)"},
]

COMMON_ROOMS = [
    "Kitchen",
    "Bedroom",
    "Bathroom",
    "Toilet",
    "Living Room",
    "Hallway",
    "Landing",
    "Study",
    "Dining Room",
    "Utility",
    "Garage",
    "Office",
]

OUTSIDE_WINDOW_ACTIONS = [
    {"value": "no_action", "label": "No action"},
    {"value": "pause", "label": "Pause automations"},
    {"value": "safe_state", "label": "Force safe state"},
]

# Optional UI dependencies used by the dashboards
DEPENDENCIES = [
    {
        "name": "HACS",
        "url": "https://hacs.xyz/",
        "domain": "hacs",
    },
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
    "condensation_danger": {"label": "Condensation Danger"},
    "humidity_danger": {"label": "Humidity Danger"},
    "mould_danger": {"label": "Mould Danger"},
    "co_emergency": {"label": "CO Emergency"},
    "custom_binary": {"label": "Custom binary sensor"},
}

# Safety guardrails for alert thresholds.
# These are enforced in config/options flow and at runtime as a fallback.
ALERT_THRESHOLD_BOUNDS = {
    "humidity_danger": {"min": 55, "max": 90, "default": 75, "unit": "%"},
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
