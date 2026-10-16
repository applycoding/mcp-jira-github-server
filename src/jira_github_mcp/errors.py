"""Errors the service and backends raise. The MCP layer maps them to tool errors."""


class ConfigError(Exception):
    """The process was started with invalid configuration."""


class ToolFailure(Exception):
    """A tool call was rejected or the backend reported a handled failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class NotFoundError(Exception):
    """The issue, pull request, or repository does not exist."""


class ConflictError(Exception):
    """The requested change is not valid for the current record."""


class BackendError(Exception):
    """A live HTTP call failed."""
