"""Pick the mock or live backends from settings."""

from jira_github_mcp.backends.github import GitHubClient, LiveGitHubClient, MockGitHubClient
from jira_github_mcp.backends.jira import JiraClient, LiveJiraClient, MockJiraClient
from jira_github_mcp.config import Settings
from jira_github_mcp.errors import ConfigError


def build_clients(settings: Settings) -> tuple[JiraClient, GitHubClient]:
    if settings.backend == "mock":
        return MockJiraClient(), MockGitHubClient()
    if settings.backend == "live":
        missing = [
            name
            for name, present in (
                ("JIRA_BASE_URL", settings.jira_base_url),
                ("JIRA_EMAIL", settings.jira_email),
                ("JIRA_API_TOKEN", settings.jira_api_token),
                ("GITHUB_TOKEN", settings.github_token),
            )
            if not present
        ]
        if missing:
            raise ConfigError("Live backend requires " + ", ".join(missing))
        if not settings.jira_base_url.startswith("https://"):
            raise ConfigError("JIRA_BASE_URL must start with https://")
        return (
            LiveJiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token),
            LiveGitHubClient(settings.github_token),
        )
    raise ConfigError("MCP_BACKEND must be mock or live")
