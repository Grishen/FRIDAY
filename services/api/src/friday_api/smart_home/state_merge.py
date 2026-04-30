"""Deep-merge dicts for smart-home partial state updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def merge_state(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, val in patch.items():
        if isinstance(val, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = merge_state(out[key], val)  # type: ignore[arg-type]
        else:
            out[key] = val
    return out
