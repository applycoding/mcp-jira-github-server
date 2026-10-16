"""JSON logs on stderr. Stdout is reserved for the MCP stdio protocol."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str)


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    logger = logging.getLogger("jira_github_mcp")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)


def log_event(level: int, event: str, **fields: object) -> None:
    logging.getLogger("jira_github_mcp").log(level, event, extra={"fields": fields})
