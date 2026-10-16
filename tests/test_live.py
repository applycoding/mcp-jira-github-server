import json

import httpx2
import pytest

from jira_github_mcp.backends.github import LiveGitHubClient
from jira_github_mcp.backends.jira import LiveJiraClient
from jira_github_mcp.errors import ConflictError, NotFoundError


def _json(status: int, payload: object) -> httpx2.Response:
    return httpx2.Response(status, json=payload)


def test_live_jira_search_create_and_comment_use_basic_auth() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path.endswith("/search/jql"):
            return _json(
                200,
                {
                    "issues": [
                        {
                            "key": "PLAT-101",
                            "fields": {
                                "summary": "SSO callback drops state",
                                "description": {
                                    "type": "doc",
                                    "content": [
                                        {
                                            "type": "paragraph",
                                            "content": [{"type": "text", "text": "Missing state"}],
                                        }
                                    ],
                                },
                                "status": {"name": "Open"},
                                "issuetype": {"name": "Bug"},
                                "project": {"key": "PLAT"},
                            },
                        }
                    ]
                },
            )
        if request.url.path.endswith("/comment"):
            return _json(201, {"id": "55"})
        return _json(201, {"key": "PLAT-103"})

    client = LiveJiraClient(
        "https://example.atlassian.net",
        "dev@example.com",
        "jira-token",
        transport=httpx2.MockTransport(handler),
    )
    page = client.search_issues("login", 5, ("PLAT",))
    assert page.issues[0].description == "Missing state"
    created = client.create_issue("PLAT", "New", "Details", "Task")
    assert created.key == "PLAT-103"
    comment = client.add_comment("PLAT-103", "Ship it")
    assert comment.id == "55"

    assert all(request.headers["authorization"].startswith("Basic ") for request in seen)
    search_body = json.loads(seen[0].content)
    assert search_body["jql"] == 'project = PLAT AND text ~ "login" ORDER BY updated DESC'
    comment_body = json.loads(seen[2].content)
    assert comment_body["body"]["type"] == "doc"
    assert comment_body["body"]["content"][0]["content"][0]["text"] == "Ship it"


def test_live_jira_transition_matches_destination_status() -> None:
    gets = {"count": 0}

    def routed(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/transitions") and request.method == "GET":
            return _json(
                200,
                {"transitions": [{"id": "21", "name": "Start", "to": {"name": "In Progress"}}]},
            )
        if request.url.path.endswith("/transitions") and request.method == "POST":
            assert json.loads(request.content) == {"transition": {"id": "21"}}
            return httpx2.Response(204)
        gets["count"] += 1
        status = "Open" if gets["count"] == 1 else "In Progress"
        return _json(
            200,
            {
                "key": "PLAT-101",
                "fields": {
                    "summary": "SSO",
                    "description": None,
                    "status": {"name": status},
                    "issuetype": {"name": "Bug"},
                    "project": {"key": "PLAT"},
                },
            },
        )

    client = LiveJiraClient(
        "https://example.atlassian.net",
        "dev@example.com",
        "jira-token",
        transport=httpx2.MockTransport(routed),
    )
    issue = client.transition_issue("PLAT-101", "In Progress")
    assert issue.status == "In Progress"


def test_live_jira_unknown_transition_lists_choices() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/transitions"):
            return _json(
                200,
                {"transitions": [{"id": "31", "name": "Done", "to": {"name": "Done"}}]},
            )
        return _json(
            200,
            {
                "key": "PLAT-101",
                "fields": {
                    "summary": "SSO",
                    "description": None,
                    "status": {"name": "Open"},
                    "issuetype": {"name": "Bug"},
                    "project": {"key": "PLAT"},
                },
            },
        )

    client = LiveJiraClient(
        "https://example.atlassian.net",
        "dev@example.com",
        "jira-token",
        transport=httpx2.MockTransport(handler),
    )
    with pytest.raises(ConflictError, match="Done"):
        client.transition_issue("PLAT-101", "In Progress")


def test_live_github_lists_summarizes_and_writes() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer github-token"
        path = request.url.path
        if path.endswith("/pulls/43/files"):
            return _json(
                200,
                [
                    {
                        "filename": "src/auth/callback.py",
                        "status": "modified",
                        "additions": 22,
                        "deletions": 6,
                    }
                ],
            )
        if path.endswith("/pulls/43"):
            return _json(
                200,
                {
                    "number": 43,
                    "title": "Reject SSO callbacks",
                    "body": "Requires state.",
                    "state": "open",
                    "user": {"login": "riley"},
                },
            )
        if path.endswith("/pulls"):
            return _json(
                200,
                [
                    {
                        "number": 43,
                        "title": "Reject SSO callbacks",
                        "body": "Requires state.",
                        "state": "open",
                        "user": {"login": "riley"},
                    }
                ],
            )
        if path.endswith("/comments"):
            return _json(201, {"id": 9, "body": "Thanks", "user": {"login": "arpan"}})
        return _json(
            201,
            {
                "number": 44,
                "title": "Docs",
                "body": "",
                "state": "open",
                "user": {"login": "arpan"},
            },
        )

    client = LiveGitHubClient("github-token", transport=httpx2.MockTransport(handler))
    pulls = client.list_pull_requests("acme", "platform", "open", 10)
    assert pulls.pull_requests[0].number == 43
    summary = client.get_pr_diff_summary("acme", "platform", 43)
    assert summary.diff_summary()["additions"] == 22
    assert summary.diff_summary()["files"][0]["summary"] == "modified src/auth/callback.py (+22 -6)"
    issue = client.create_issue("acme", "platform", "Docs", "")
    assert issue.number == 44
    comment = client.add_comment("acme", "platform", 43, "Thanks")
    assert comment.author == "arpan"


def test_live_github_404_is_not_found() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _json(404, {"message": "Not Found"})

    client = LiveGitHubClient("github-token", transport=httpx2.MockTransport(handler))
    with pytest.raises(NotFoundError):
        client.get_pr_diff_summary("acme", "missing", 1)
