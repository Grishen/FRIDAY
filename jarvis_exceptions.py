"""Exceptions shared across the voice assistant (avoids circular imports)."""


class JarvisExitRequest(Exception):
    """User asked to exit the voice session (clean shutdown)."""

