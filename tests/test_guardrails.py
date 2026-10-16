import io
import json

import pytest

from jira_github_mcp.config import Settings
from jira_github_mcp.errors import ToolFailure
from jira_github_mcp.models import IssuePage, JiraIssue
from jira_github_mcp.rate_limit import RateLimiter
from jira_github_mcp.service import build_service
from jira_github_mcp.structured_log import configure_logging


def test_read_only_blocks_writes_and_keeps_reads() -> None:
    service = build_service(Settings(read_only=True))
    found = service.call("jira_search_issues", {"query": "project:PLAT"})
    assert found["total"] == 2
    with pytest.raises(ToolFailure) as exc:
        service.call(
            "jira_create_issue",
            {"project": "PLAT", "summary": "Should not exist", "issue_type": "Task"},
        )
    assert exc.value.code == "read_only"
    again = service.call("jira_search_issues", {"query": "project:PLAT"})
    assert again == found


def test_tool_allowlist_rejects_other_tools() -> None:
    service = build_service(Settings(tool_allowlist=("jira_search_issues",)))
    service.call("jira_search_issues", {"query": "login"})
    with pytest.raises(ToolFailure) as exc:
        service.call(
            "github_list_pull_requests",
            {"owner": "acme", "repo": "platform"},
        )
    assert exc.value.code == "not_allowed"


def test_project_allowlist_filters_search_and_blocks_creates() -> None:
    service = build_service(Settings(jira_project_allowlist=("PLAT",)))
    result = service.call("jira_search_issues", {"query": "status:Open"})
    assert [issue["key"] for issue in result["issues"]] == ["PLAT-101"]
    with pytest.raises(ToolFailure) as exc:
        service.call(
            "jira_add_comment",
            {"issue_key": "MOB-14", "body": "out of scope"},
        )
    assert exc.value.code == "not_allowed"


def test_search_filters_client_results_outside_the_allowlist() -> None:
    class MixedJira:
        def search_issues(
            self, query: str, max_results: int, projects: tuple[str, ...]
        ) -> IssuePage:
            return IssuePage(
                issues=[
                    JiraIssue("MOB-1", "MOB", "Mobile", "", "Task", "Open"),
                    JiraIssue("PLAT-1", "PLAT", "Platform", "", "Task", "Open"),
                ],
                total=2,
            )

        def create_issue(
            self, project: str, summary: str, description: str, issue_type: str
        ) -> JiraIssue:
            raise AssertionError

        def add_comment(self, issue_key: str, body: str) -> object:
            raise AssertionError

        def transition_issue(self, issue_key: str, status: str) -> JiraIssue:
            raise AssertionError

    service = build_service(Settings(jira_project_allowlist=("PLAT",)), jira=MixedJira())
    result = service.call("jira_search_issues", {"query": "status:Open"})
    assert [issue["key"] for issue in result["issues"]] == ["PLAT-1"]
    assert result["total"] == 1


def test_repo_allowlist() -> None:
    service = build_service(Settings(github_repo_allowlist=("acme/platform",)))
    listed = service.call(
        "github_list_pull_requests",
        {"owner": "acme", "repo": "platform", "state": "all"},
    )
    assert listed["total"] == 3
    with pytest.raises(ToolFailure) as exc:
        service.call(
            "github_list_pull_requests",
            {"owner": "acme", "repo": "other"},
        )
    assert exc.value.code == "not_allowed"


def test_rate_limit_resets_after_the_window() -> None:
    clock = {"now": 1_000.0}
    limiter = RateLimiter(2, window_seconds=60, clock=lambda: clock["now"])
    service = build_service(Settings(rate_limit_per_minute=2), rate_limiter=limiter)
    service.call("jira_search_issues", {"query": "login"})
    service.call("jira_search_issues", {"query": "login"})
    with pytest.raises(ToolFailure) as exc:
        service.call("jira_search_issues", {"query": "login"})
    assert exc.value.code == "rate_limited"
    clock["now"] = 1_061.0
    service.call("jira_search_issues", {"query": "login"})


def test_zero_rate_limit_disables_the_budget() -> None:
    service = build_service(Settings(rate_limit_per_minute=0))
    for _ in range(5):
        service.call("jira_search_issues", {"query": "login"})


def test_logs_omit_argument_values() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream)
    service = build_service(Settings())
    service.call("jira_search_issues", {"query": "login"})
    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "tool_call"
    assert payload["tool"] == "jira_search_issues"
    assert payload["ok"] is True
    assert "login" not in line


def test_unknown_tool() -> None:
    service = build_service(Settings())
    with pytest.raises(ToolFailure) as exc:
        service.call("delete_repository", {})
    assert exc.value.code == "unknown_tool"
