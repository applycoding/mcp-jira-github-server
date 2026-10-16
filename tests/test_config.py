import pytest

from jira_github_mcp.config import Settings
from jira_github_mcp.errors import ConfigError
from jira_github_mcp.service import build_service


def test_defaults_need_no_credentials() -> None:
    settings = Settings.from_env({})
    assert settings.backend == "mock"
    assert settings.read_only is False
    assert settings.rate_limit_per_minute == 60
    assert settings.tool_allowlist == ()


def test_flags_and_allowlists_are_normalized() -> None:
    settings = Settings.from_env(
        {
            "MCP_BACKEND": "LIVE",
            "MCP_READ_ONLY": "yes",
            "MCP_TOOL_ALLOWLIST": "jira_search_issues, jira_search_issues",
            "JIRA_PROJECT_ALLOWLIST": "plat, PLAT",
            "GITHUB_REPO_ALLOWLIST": "Acme/Platform",
            "MCP_RATE_LIMIT_PER_MINUTE": "0",
            "LOG_LEVEL": "debug",
            "JIRA_BASE_URL": "https://example.atlassian.net/",
        }
    )
    assert settings.backend == "live"
    assert settings.read_only is True
    assert settings.tool_allowlist == ("jira_search_issues",)
    assert settings.jira_project_allowlist == ("PLAT",)
    assert settings.github_repo_allowlist == ("acme/platform",)
    assert settings.rate_limit_per_minute == 0
    assert settings.log_level == "DEBUG"
    assert settings.jira_base_url == "https://example.atlassian.net"


@pytest.mark.parametrize(
    "env",
    [
        {"MCP_BACKEND": "staging"},
        {"MCP_READ_ONLY": "maybe"},
        {"MCP_TOOL_ALLOWLIST": "drop_database"},
        {"JIRA_PROJECT_ALLOWLIST": "1"},
        {"GITHUB_REPO_ALLOWLIST": "not a repo"},
        {"MCP_RATE_LIMIT_PER_MINUTE": "-1"},
        {"LOG_LEVEL": "verbose"},
    ],
)
def test_invalid_env_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_live_mode_requires_https_and_tokens() -> None:
    with pytest.raises(ConfigError, match="JIRA_BASE_URL"):
        build_service(Settings(backend="live"))
    with pytest.raises(ConfigError, match="https://"):
        build_service(
            Settings(
                backend="live",
                jira_base_url="http://example.atlassian.net",
                jira_email="dev@example.com",
                jira_api_token="token",
                github_token="token",
            )
        )
