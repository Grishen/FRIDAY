"""Secrets provider abstraction — swap implementations per environment."""

from __future__ import annotations

from typing import Protocol


class SecretsProvider(Protocol):
    def get_optional(self, key: str) -> str | None: ...

    def require(self, key: str) -> str:
        val = self.get_optional(key)
        if not val:
            raise KeyError(key)
        return val


class EnvSecretsProvider:
    """Reads directly from OS environment (bootstrap only)."""

    def get_optional(self, key: str) -> str | None:
        import os

        return os.environ.get(key)

    def require(self, key: str) -> str:
        v = self.get_optional(key)
        if not v:
            raise KeyError(key)
        return v
