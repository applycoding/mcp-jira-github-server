"""Jira backends. The mock store is the default. Live mode talks to Jira Cloud."""

from __future__ import annotations

import threading
from typing import Protocol

import httpx2

from jira_github_mcp.backends.http import send_json
from jira_github_mcp.errors import BackendError, ConflictError, NotFoundError
from jira_github_mcp.models import IssuePage, JiraComment, JiraIssue
from jira_github_mcp.query import parse_query, to_jql

MOCK_ISSUE_TYPES = ("Bug", "Task", "Story")
_TRANSITIONS: dict[str, set[str]] = {
    "Open": {"In Progress", "Done"},
    "In Progress": {"In Review", "Open"},
    "In Review": {"Done", "In Progress"},
    "Done": set(),
}


class JiraClient(Protocol):
    def search_issues(
        self, query: str, max_results: int, projects: tuple[str, ...]
    ) -> IssuePage: ...

    def create_issue(
        self, project: str, summary: str, description: str, issue_type: str
    ) -> JiraIssue: ...

    def add_comment(self, issue_key: str, body: str) -> JiraComment: ...

    def transition_issue(self, issue_key: str, status: str) -> JiraIssue: ...


def _seed_issues() -> list[JiraIssue]:
    return [
        JiraIssue(
            key="PLAT-101",
            project="PLAT",
            summary="SSO callback drops state and returns 500",
            description=(
                "The login callback accepts a request that is missing the state parameter "
                "and responds with HTTP 500. Reject the callback before the code is exchanged."
            ),
            issue_type="Bug",
            status="Open",
            comments=[
                JiraComment(
                    id="10001",
                    author="riley",
                    body="Reproduced against the mock identity provider.",
                )
            ],
        ),
        JiraIssue(
            key="PLAT-102",
            project="PLAT",
            summary="Record an audit event for every agent tool call",
            description=(
                "Write a structured audit event for each Jira and GitHub tool call. "
                "Keep tokens and argument values out of the log line."
            ),
            issue_type="Story",
            status="In Progress",
        ),
        JiraIssue(
            key="MOB-14",
            project="MOB",
            summary="Cache GitHub pull request summaries for the mobile review bot",
            description=(
                "The mobile client refetches the same pull request diff summary on every open."
            ),
            issue_type="Task",
            status="Open",
        ),
    ]


def _matches(issue: JiraIssue, filters: dict[str, str], text: str) -> bool:
    checks = {
        "project": issue.project,
        "status": issue.status,
        "type": issue.issue_type,
        "key": issue.key,
    }
    for field, expected in filters.items():
        if checks[field].lower() != expected.lower():
            return False
    if not text:
        return True
    haystack = " ".join(
        (issue.key, issue.summary, issue.description, issue.status, issue.issue_type)
    ).lower()
    return all(token in haystack for token in text.lower().split())


class MockJiraClient:
    """In-memory Jira project used by the demo and the unit tests."""

    def __init__(self) -> None:
        self._issues = {issue.key: issue for issue in _seed_issues()}
        sequences: dict[str, int] = {}
        for issue in self._issues.values():
            number = int(issue.key.split("-")[1])
            sequences[issue.project] = max(sequences.get(issue.project, 0), number)
        self._sequences = sequences
        self._comment_seq = 10001
        self._lock = threading.Lock()

    def search_issues(self, query: str, max_results: int, projects: tuple[str, ...]) -> IssuePage:
        filters, text = parse_query(query)
        allowed = {project.upper() for project in projects}
        with self._lock:
            matched = [
                issue
                for issue in self._issues.values()
                if (not allowed or issue.project in allowed) and _matches(issue, filters, text)
            ]
        matched.sort(key=lambda issue: issue.key)
        return IssuePage(issues=matched[:max_results], total=len(matched))

    def create_issue(
        self, project: str, summary: str, description: str, issue_type: str
    ) -> JiraIssue:
        if issue_type not in MOCK_ISSUE_TYPES:
            raise ConflictError(f"Unsupported issue type {issue_type}")
        with self._lock:
            number = self._sequences.get(project, 100) + 1
            self._sequences[project] = number
            issue = JiraIssue(
                key=f"{project}-{number}",
                project=project,
                summary=summary,
                description=description,
                issue_type=issue_type,
                status="Open",
            )
            self._issues[issue.key] = issue
            return issue

    def add_comment(self, issue_key: str, body: str) -> JiraComment:
        with self._lock:
            issue = self._issues.get(issue_key)
            if issue is None:
                raise NotFoundError(f"Jira issue {issue_key} was not found")
            self._comment_seq += 1
            comment = JiraComment(id=str(self._comment_seq), body=body, author="agent")
            issue.comments.append(comment)
            return comment

    def transition_issue(self, issue_key: str, status: str) -> JiraIssue:
        with self._lock:
            issue = self._issues.get(issue_key)
            if issue is None:
                raise NotFoundError(f"Jira issue {issue_key} was not found")
            if issue.status.lower() == status.lower():
                return issue
            allowed = _TRANSITIONS.get(issue.status, set())
            match = next((name for name in allowed if name.lower() == status.lower()), None)
            if match is None:
                choices = ", ".join(sorted(allowed)) or "none"
                raise ConflictError(
                    f"Cannot transition {issue_key} from {issue.status} to {status}. "
                    f"Available: {choices}"
                )
            issue.status = match
            return issue


def _adf(text: str) -> dict[str, object]:
    paragraphs: list[dict[str, object]] = []
    for paragraph in text.split("\n") or [""]:
        content: list[dict[str, str]] = []
        if paragraph:
            content.append({"type": "text", "text": paragraph})
        paragraphs.append({"type": "paragraph", "content": content})
    return {"type": "doc", "version": 1, "content": paragraphs}


def _adf_text(node: object) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    children = node.get("content", [])
    if not isinstance(children, list):
        return ""
    return "\n".join(part for part in (_adf_text(child) for child in children) if part)


def _issue_from_payload(payload: dict[str, object]) -> JiraIssue:
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        raise BackendError("Jira issue payload is missing fields")
    key = str(payload.get("key", ""))
    project = fields.get("project")
    status = fields.get("status")
    issue_type = fields.get("issuetype")
    project_key = project.get("key") if isinstance(project, dict) else ""
    status_name = status.get("name") if isinstance(status, dict) else ""
    type_name = issue_type.get("name") if isinstance(issue_type, dict) else ""
    if not key or not project_key:
        raise BackendError("Jira issue payload is missing a key")
    return JiraIssue(
        key=key,
        project=str(project_key),
        summary=str(fields.get("summary") or ""),
        description=_adf_text(fields.get("description")),
        issue_type=str(type_name or "Task"),
        status=str(status_name or "Open"),
    )


class LiveJiraClient:
    """Thin Jira Cloud REST client. Basic auth is email plus an API token."""

    def __init__(
        self,
        base_url: str,
        email: str,
        token: str,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._http = httpx2.Client(
            base_url=base_url.rstrip("/"),
            auth=(email, token),
            headers={"Accept": "application/json"},
            transport=transport,
            timeout=20.0,
        )

    def search_issues(self, query: str, max_results: int, projects: tuple[str, ...]) -> IssuePage:
        payload = send_json(
            self._http,
            "POST",
            "/rest/api/3/search/jql",
            json_body={
                "jql": to_jql(query, projects),
                "maxResults": max_results,
                "fields": ["summary", "status", "issuetype", "description", "project"],
            },
            not_found="Jira search failed",
        )
        issues = payload.get("issues") if isinstance(payload, dict) else None
        if not isinstance(issues, list):
            raise BackendError("Jira search response is missing issues")
        parsed = [_issue_from_payload(item) for item in issues if isinstance(item, dict)]
        return IssuePage(issues=parsed, total=len(parsed))

    def create_issue(
        self, project: str, summary: str, description: str, issue_type: str
    ) -> JiraIssue:
        payload = send_json(
            self._http,
            "POST",
            "/rest/api/3/issue",
            json_body={
                "fields": {
                    "project": {"key": project},
                    "summary": summary,
                    "issuetype": {"name": issue_type},
                    "description": _adf(description),
                }
            },
            not_found=f"Jira project {project} was not found",
        )
        if not isinstance(payload, dict) or "key" not in payload:
            raise BackendError("Jira create response is missing a key")
        return JiraIssue(
            key=str(payload["key"]),
            project=project,
            summary=summary,
            description=description,
            issue_type=issue_type,
            status="Open",
        )

    def add_comment(self, issue_key: str, body: str) -> JiraComment:
        payload = send_json(
            self._http,
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            json_body={"body": _adf(body)},
            not_found=f"Jira issue {issue_key} was not found",
        )
        if not isinstance(payload, dict) or "id" not in payload:
            raise BackendError("Jira comment response is missing an id")
        return JiraComment(id=str(payload["id"]), body=body, author="agent")

    def transition_issue(self, issue_key: str, status: str) -> JiraIssue:
        current = self._get_issue(issue_key)
        if current.status.lower() == status.lower():
            return current
        payload = send_json(
            self._http,
            "GET",
            f"/rest/api/3/issue/{issue_key}/transitions",
            not_found=f"Jira issue {issue_key} was not found",
        )
        transitions = payload.get("transitions") if isinstance(payload, dict) else None
        if not isinstance(transitions, list):
            raise BackendError("Jira transitions response is missing transitions")
        match = _matching_transition(transitions, status)
        if match is None:
            names = sorted(
                {
                    str(item.get("name"))
                    for item in transitions
                    if isinstance(item, dict) and item.get("name")
                }
            )
            available = ", ".join(names) or "none"
            raise ConflictError(
                f"Cannot transition {issue_key} to {status}. Available: {available}"
            )
        send_json(
            self._http,
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json_body={"transition": {"id": match}},
            not_found=f"Jira issue {issue_key} was not found",
        )
        return self._get_issue(issue_key)

    def _get_issue(self, issue_key: str) -> JiraIssue:
        payload = send_json(
            self._http,
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            not_found=f"Jira issue {issue_key} was not found",
        )
        if not isinstance(payload, dict):
            raise BackendError("Jira issue response was not an object")
        return _issue_from_payload(payload)


def _matching_transition(transitions: list[object], status: str) -> str | None:
    wanted = status.lower()
    for item in transitions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        destination = item.get("to")
        destination_name = destination.get("name") if isinstance(destination, dict) else ""
        if name.lower() == wanted or str(destination_name).lower() == wanted:
            return str(item.get("id"))
    return None
