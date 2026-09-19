"""Exception types raised by the engine."""

from __future__ import annotations


class TrailGuideError(Exception):
    """Base class for all engine errors."""


class ConfigError(TrailGuideError):
    """Raised when a client configuration is missing or invalid."""


class ConnectorError(TrailGuideError):
    """Raised when a source cannot be read or normalized."""


class UnknownSourceError(ConnectorError):
    """Raised when a configured source type has no registered connector."""
