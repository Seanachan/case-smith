"""Structural validation of model output.

Structure is guaranteed here, never by the prompt.
"""

from __future__ import annotations

import json

from pipeline.seed_planner import ModelSlot

_SCALAR = (str, int, float, bool, type(None))


class SchemaError(Exception):
    """Model output violates the required flat-JSON shape."""


def _extract_json_block(raw: str) -> str:
    """Return the first balanced {...} block (models add chatter around JSON)."""
    start = raw.find("{")
    if start == -1:
        raise SchemaError("no '{' found in model output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    raise SchemaError("unbalanced '{' in model output")


def _parse_object(raw: str) -> dict:
    block = _extract_json_block(raw)
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SchemaError(f"expected JSON object, got {type(data).__name__}")
    return data


def parse_flat_json(raw: str, slots: list[ModelSlot]) -> dict:
    """Flat object whose keys are exactly the slot names."""
    data = _parse_object(raw)
    for key, value in data.items():
        if not isinstance(value, _SCALAR):
            raise SchemaError(f"nested value at key {key!r}; flat JSON required")
    expected = {s.name for s in slots}
    got = set(data)
    if got != expected:
        raise SchemaError(
            f"key mismatch; missing={sorted(expected - got)} "
            f"extra={sorted(got - expected)}")
    return data


def validate_patch(raw: str, allowed_fields: set) -> dict:
    """Exactly {"field": ..., "value": ...} with field in the allowlist."""
    data = _parse_object(raw)
    if set(data) != {"field", "value"}:
        raise SchemaError('patch must be exactly {"field": ..., "value": ...}')
    if data["field"] not in allowed_fields:
        raise SchemaError(f"field {data['field']!r} not in allowed fields")
    return data
