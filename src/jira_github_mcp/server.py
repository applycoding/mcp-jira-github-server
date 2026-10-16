"""MCP server. Tool functions stay thin and delegate to ToolService."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from jira_github_mcp import __version__
from jira_github_mcp.config import Settings
from jira_github_mcp.errors import ToolFailure
from jira_github_mcp.service import ToolService, build_service
from jira_github_mcp.structured_log import configure_logging

_Query = Annotated[str, Field(min_length=1, max_length=500)]
_Page = Annotated[int, Field(ge=1, le=50)]
_Project = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")]
_Summary = Annotated[str, Field(min_length=1, max_length=255)]
_Body = Annotated[str, Field(max_length=10000)]
_Comment = Annotated[str, Field(min_length=1, max_length=10000)]
_IssueKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")]
_Status = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9 _-]{0,39}$")]
_Owner = Annotated[str, Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")]
_Repo = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")]
_Number = Annotated[int, Field(ge=1)]


def _run(service: ToolService, name: str, arguments: dict[str, Any]) -> str:
    try:
        result = service.call(name, arguments)
    except ToolFailure as exc:
        raise ToolError(f"{exc.code}: {exc}") from exc
    return json.dumps(result, indent=2)


def build_server(settings: Settings | None = None) -> MCPServer:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)
    service = build_service(resolved)
    server = MCPServer(
        name="jira-github",
        title="Jira and GitHub",
        version=__version__,
        instructions=(
            "Demo MCP server for Jira and GitHub. The default backend is in-memory mock data. "
            "Write tools fail when read-only mode is on. "
            "Jira search accepts project:, status:, type:, and key: filters plus free text. "
            "Pass a string that contains = or ~ to send raw JQL in live mode."
        ),
    )
    _register_tools(server, service)
    return server


def _register_tools(server: MCPServer, service: ToolService) -> None:
    allowed = set(service.settings.tool_allowlist)

    def expose(
        name: str,
        fn: Callable[..., str],
        description: str,
        annotations: ToolAnnotations,
    ) -> None:
        if allowed and name not in allowed:
            return
        server.add_tool(
            fn,
            name=name,
            description=description,
            annotations=annotations,
            structured_output=False,
        )

    def jira_search_issues(query: _Query, max_results: _Page = 10) -> str:
        return _run(service, "jira_search_issues", {"query": query, "max_results": max_results})

    def jira_create_issue(
        project: _Project,
        summary: _Summary,
        description: _Body = "",
        issue_type: Literal["Bug", "Task", "Story"] = "Task",
    ) -> str:
        return _run(
            service,
            "jira_create_issue",
            {
                "project": project,
                "summary": summary,
                "description": description,
                "issue_type": issue_type,
            },
        )

    def jira_add_comment(issue_key: _IssueKey, body: _Comment) -> str:
        return _run(service, "jira_add_comment", {"issue_key": issue_key, "body": body})

    def jira_transition_issue(issue_key: _IssueKey, status: _Status) -> str:
        return _run(service, "jira_transition_issue", {"issue_key": issue_key, "status": status})

    def github_list_pull_requests(
        owner: _Owner,
        repo: _Repo,
        state: Literal["open", "closed", "all"] = "open",
        max_results: _Page = 10,
    ) -> str:
        return _run(
            service,
            "github_list_pull_requests",
            {"owner": owner, "repo": repo, "state": state, "max_results": max_results},
        )

    def github_get_pr_diff_summary(owner: _Owner, repo: _Repo, number: _Number) -> str:
        return _run(
            service,
            "github_get_pr_diff_summary",
            {"owner": owner, "repo": repo, "number": number},
        )

    def github_create_issue(owner: _Owner, repo: _Repo, title: _Summary, body: _Body = "") -> str:
        return _run(
            service,
            "github_create_issue",
            {"owner": owner, "repo": repo, "title": title, "body": body},
        )

    def github_add_comment(owner: _Owner, repo: _Repo, number: _Number, body: _Comment) -> str:
        return _run(
            service,
            "github_add_comment",
            {"owner": owner, "repo": repo, "number": number, "body": body},
        )

    expose(
        "jira_search_issues",
        jira_search_issues,
        "Search Jira issues. Use project:KEY, status:\"Name\", type:Bug, key:KEY-1, or free text.",
        ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "jira_create_issue",
        jira_create_issue,
        "Create a Jira issue. issue_type is Bug, Task, or Story. New issues start as Open.",
        ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "jira_add_comment",
        jira_add_comment,
        "Add a comment to a Jira issue key such as PLAT-101.",
        ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "jira_transition_issue",
        jira_transition_issue,
        "Move a Jira issue to a status. Mock workflow: Open, In Progress, In Review, Done.",
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    expose(
        "github_list_pull_requests",
        github_list_pull_requests,
        "List pull requests in a repository. state is open, closed, or all.",
        ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "github_get_pr_diff_summary",
        github_get_pr_diff_summary,
        "Summarize a pull request diff: files changed, additions, deletions, and a short overview.",
        ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "github_create_issue",
        github_create_issue,
        "Open a GitHub issue in owner/repo.",
        ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    )
    expose(
        "github_add_comment",
        github_add_comment,
        "Comment on a GitHub issue or pull request number.",
        ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True),
    )
