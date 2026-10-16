"""Environment configuration. Tokens are read from the environment and never logged."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from jira_github_mcp.catalog import TOOL_NAMES
from jira_github_mcp.errors import ConfigError

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_PROJECT = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_REPO = re.compile(r"^[a-z0-9_.-]+/[a-z0-9_.-]+$")


def _flag(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{key} must be true or false, got {raw!r}")


def _csv(env: Mapping[str, str], key: str) -> tuple[str, ...]:
    raw = env.get(key, "")
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(dict.fromkeys(parts))


def _limit(env: Mapping[str, str]) -> int:
    raw = env.get("MCP_RATE_LIMIT_PER_MINUTE", "").strip()
    if raw == "":
        return 60
    if not raw.isdigit():
        raise ConfigError("MCP_RATE_LIMIT_PER_MINUTE must be a non-negative integer")
    return int(raw)


@dataclass(frozen=True, slots=True)
class Settings:
    backend: Literal["mock", "live"] = "mock"
    read_only: bool = False
    tool_allowlist: tuple[str, ...] = ()
    jira_project_allowlist: tuple[str, ...] = ()
    github_repo_allowlist: tuple[str, ...] = ()
    rate_limit_per_minute: int = 60
    log_level: str = "INFO"
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    github_token: str = ""

    def __post_init__(self) -> None:
        backend = self.backend.lower()
        if backend not in {"mock", "live"}:
            raise ConfigError("MCP_BACKEND must be mock or live")
        object.__setattr__(self, "backend", backend)

        level = self.log_level.upper()
        if level not in _LEVELS:
            raise ConfigError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        object.__setattr__(self, "log_level", level)

        if self.rate_limit_per_minute < 0:
            raise ConfigError("MCP_RATE_LIMIT_PER_MINUTE must be a non-negative integer")

        unknown = [name for name in self.tool_allowlist if name not in TOOL_NAMES]
        if unknown:
            raise ConfigError("Unknown tool in MCP_TOOL_ALLOWLIST: " + ", ".join(unknown))

        projects: list[str] = []
        for project in self.jira_project_allowlist:
            key = project.upper()
            if not _PROJECT.fullmatch(key):
                raise ConfigError(f"Invalid Jira project in JIRA_PROJECT_ALLOWLIST: {project}")
            projects.append(key)
        object.__setattr__(self, "jira_project_allowlist", tuple(dict.fromkeys(projects)))

        repos: list[str] = []
        for repo in self.github_repo_allowlist:
            slug = repo.lower()
            if not _REPO.fullmatch(slug):
                raise ConfigError(f"Invalid repository in GITHUB_REPO_ALLOWLIST: {repo}")
            repos.append(slug)
        object.__setattr__(self, "github_repo_allowlist", tuple(dict.fromkeys(repos)))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        backend = source.get("MCP_BACKEND", "").strip().lower() or "mock"
        return cls(
            backend=backend,  # type: ignore[arg-type]
            read_only=_flag(source, "MCP_READ_ONLY", False),
            tool_allowlist=_csv(source, "MCP_TOOL_ALLOWLIST"),
            jira_project_allowlist=_csv(source, "JIRA_PROJECT_ALLOWLIST"),
            github_repo_allowlist=_csv(source, "GITHUB_REPO_ALLOWLIST"),
            rate_limit_per_minute=_limit(source),
            log_level=source.get("LOG_LEVEL", "INFO"),
            jira_base_url=source.get("JIRA_BASE_URL", "").strip().rstrip("/"),
            jira_email=source.get("JIRA_EMAIL", "").strip(),
            jira_api_token=source.get("JIRA_API_TOKEN", "").strip(),
            github_token=source.get("GITHUB_TOKEN", "").strip(),
        )
