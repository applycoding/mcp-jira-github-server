"""Tool names shared by configuration, the service, and the MCP server."""

from typing import Literal

ToolName = Literal[
    "jira_search_issues",
    "jira_create_issue",
    "jira_add_comment",
    "jira_transition_issue",
    "github_list_pull_requests",
    "github_get_pr_diff_summary",
    "github_create_issue",
    "github_add_comment",
]

TOOL_NAMES: tuple[ToolName, ...] = (
    "jira_search_issues",
    "jira_create_issue",
    "jira_add_comment",
    "jira_transition_issue",
    "github_list_pull_requests",
    "github_get_pr_diff_summary",
    "github_create_issue",
    "github_add_comment",
)

WRITE_TOOLS: frozenset[ToolName] = frozenset(
    {
        "jira_create_issue",
        "jira_add_comment",
        "jira_transition_issue",
        "github_create_issue",
        "github_add_comment",
    }
)
