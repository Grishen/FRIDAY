from __future__ import annotations

from enum import Enum


class MemoryType(str, Enum):
    PROFILE = "profile"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    TASK = "task"


class SensitivityLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
