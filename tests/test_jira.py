import pytest

from jira_github_mcp.errors import ToolFailure
from jira_github_mcp.service import ToolService


def test_search_finds_the_sso_bug(service: ToolService) -> None:
    result = service.call("jira_search_issues", {"query": "login"})
    assert result["total"] == 1
    issue = result["issues"][0]
    assert issue["key"] == "PLAT-101"
    assert issue["status"] == "Open"
    assert issue["comment_count"] == 1


def test_field_filters_combine(service: ToolService) -> None:
    open_issues = service.call("jira_search_issues", {"query": "status:Open"})
    assert {issue["key"] for issue in open_issues["issues"]} == {"PLAT-101", "MOB-14"}
    in_progress = service.call("jira_search_issues", {"query": 'status:"In Progress"'})
    assert [issue["key"] for issue in in_progress["issues"]] == ["PLAT-102"]


def test_create_comment_and_transition(service: ToolService) -> None:
    created = service.call(
        "jira_create_issue",
        {
            "project": "PLAT",
            "summary": "Note the demo boundary",
            "description": "This issue exists only in the mock store.",
            "issue_type": "Task",
        },
    )
    assert created["key"] == "PLAT-103"
    assert created["status"] == "Open"

    comment = service.call(
        "jira_add_comment",
        {"issue_key": "PLAT-103", "body": "Mock comment from the agent."},
    )
    assert comment["comment"]["author"] == "agent"
    assert comment["comment"]["body"] == "Mock comment from the agent."

    moved = service.call(
        "jira_transition_issue",
        {"issue_key": "PLAT-103", "status": "In Progress"},
    )
    assert moved["status"] == "In Progress"
    again = service.call(
        "jira_transition_issue",
        {"issue_key": "PLAT-103", "status": "In Progress"},
    )
    assert again["status"] == "In Progress"


def test_unknown_issue_and_illegal_transition(service: ToolService) -> None:
    with pytest.raises(ToolFailure) as missing:
        service.call("jira_add_comment", {"issue_key": "PLAT-999", "body": "hello"})
    assert missing.value.code == "not_found"

    with pytest.raises(ToolFailure) as blocked:
        service.call("jira_transition_issue", {"issue_key": "PLAT-102", "status": "Done"})
    assert blocked.value.code == "conflict"
    assert "In Review" in str(blocked.value)


def test_invalid_issue_key_is_rejected(service: ToolService) -> None:
    with pytest.raises(ToolFailure) as exc:
        service.call("jira_add_comment", {"issue_key": "drop table", "body": "nope"})
    assert exc.value.code == "invalid_input"
