import pytest

from jira_github_mcp.errors import ToolFailure
from jira_github_mcp.service import ToolService


def test_list_pull_requests_filters_by_state(service: ToolService) -> None:
    opened = service.call(
        "github_list_pull_requests",
        {"owner": "acme", "repo": "platform", "state": "open"},
    )
    assert [pull["number"] for pull in opened["pull_requests"]] == [42, 43]
    closed = service.call(
        "github_list_pull_requests",
        {"owner": "acme", "repo": "platform", "state": "closed"},
    )
    assert [pull["number"] for pull in closed["pull_requests"]] == [41]


def test_diff_summary_totals_the_seeded_files(service: ToolService) -> None:
    summary = service.call(
        "github_get_pr_diff_summary",
        {"owner": "Acme", "repo": "Platform", "number": 42},
    )
    assert summary["files_changed"] == 3
    assert summary["additions"] == 160
    assert summary["deletions"] == 0
    assert summary["files"][0]["filename"] == "src/audit/log.py"


def test_create_issue_and_comment(service: ToolService) -> None:
    created = service.call(
        "github_create_issue",
        {
            "owner": "acme",
            "repo": "platform",
            "title": "Document the demo",
            "body": "Mock issue only.",
        },
    )
    assert created["number"] == 44
    assert created["state"] == "open"
    comment = service.call(
        "github_add_comment",
        {"owner": "acme", "repo": "platform", "number": 43, "body": "Looks good to me."},
    )
    assert comment["comment"]["body"] == "Looks good to me."
    assert comment["number"] == 43


def test_missing_pull_request_and_unknown_repo(service: ToolService) -> None:
    with pytest.raises(ToolFailure) as missing:
        service.call(
            "github_get_pr_diff_summary",
            {"owner": "acme", "repo": "platform", "number": 7},
        )
    assert missing.value.code == "not_found"

    with pytest.raises(ToolFailure) as unknown:
        service.call(
            "github_list_pull_requests",
            {"owner": "acme", "repo": "other", "state": "open"},
        )
    assert unknown.value.code == "not_found"
