"""Shared diagnostics redaction helpers for Humidity Intelligence."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data

TO_REDACT = (
    "access_key",
    "access_token",
    "address",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "credentials",
    "credential_json",
    "device_id",
    "device_ids",
    "email",
    "external_url",
    "gps_accuracy",
    "host",
    "host_name",
    "hostname",
    "internal_url",
    "ip",
    "ip_address",
    "latitude",
    "long_lived_access_token",
    "longitude",
    "mac",
    "mac_address",
    "password",
    "phone",
    "postal_code",
    "postcode",
    "refresh_token",
    "secret",
    "secrets",
    "ssid",
    "street",
    "street_address",
    "token",
    "unique_id",
    "unique_ids",
    "output_identity",
    "source_identity",
    "confirmations",
    "retired",
    "url",
    "user",
    "username",
    "webhook_id",
    "webhook_url",
)

_SENSITIVE_KEY_PARTS = (
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "address",
    "external_url",
    "device_id",
    "internal_url",
    "host_name",
    "hostname",
    "ip_address",
    "latitude",
    "longitude",
    "long_lived_access_token",
    "mac_address",
    "password",
    "refresh_token",
    "secret",
    "street_address",
    "token",
    "unique_id",
    "webhook",
)
_URL_RE = re.compile(r"(?i)\b(?:https?|wss?|mqtt)://[^\s)>\"]+")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access_token|api_key|apikey|auth|key|password|secret|signature|sig|token)=)[^&#\s]+"
)


def redact_diagnostics_payload(value: Any) -> Any:
    """Return a JSON-safe diagnostics payload with HI and HA redaction applied."""
    sanitized = _sanitize_sensitive(_to_jsonable(value))
    return async_redact_data(sanitized, TO_REDACT)


def _sanitize_sensitive(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_sensitive(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_sensitive(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in TO_REDACT or any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _sanitize_string(value: str) -> str:
    text = _BEARER_RE.sub("Bearer [REDACTED]", value)
    text = _QUERY_SECRET_RE.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    return _URL_RE.sub("[REDACTED_URL]", text)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "items"):
        try:
            return {str(key): _to_jsonable(item) for key, item in value.items()}
        except (AttributeError, TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    return str(value)
