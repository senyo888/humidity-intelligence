"""Voluptuous validators for Humidity Intelligence."""

from __future__ import annotations

import voluptuous as vol


def bounded_float(min_value: float, max_value: float) -> vol.Schema:
    """Return a schema that validates a float within a range."""

    def validate(value: float) -> float:
        try:
            fval = float(value)
        except (TypeError, ValueError):
            raise vol.Invalid(f"{value!r} is not a valid number")
        if fval < min_value or fval > max_value:
            raise vol.Invalid(f"Value {fval} out of range [{min_value}, {max_value}]")
        return fval

    return vol.Schema(validate)


def bounded_int(min_value: int, max_value: int) -> vol.Schema:
    """Return a schema that validates an int within a range."""

    def validate(value: int) -> int:
        try:
            ival = int(value)
        except (TypeError, ValueError):
            raise vol.Invalid(f"{value!r} is not a valid integer")
        if ival < min_value or ival > max_value:
            raise vol.Invalid(f"Value {ival} out of range [{min_value}, {max_value}]")
        return ival

    return vol.Schema(validate)
