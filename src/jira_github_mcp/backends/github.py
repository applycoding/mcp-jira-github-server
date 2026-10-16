"""GitHub backends. The mock store is the default. Live mode uses the REST API."""

from __future__ import annotations

import threading
from typing import Protocol
from urllib.parse import quote

import httpx2

from jira_github_mcp.backends.http import send_json
from jira_github_mcp.errors import BackendError, NotFoundError
from jira_github_mcp.models import DiffFile, GitHubComment, GitHubIssue, PullPage, PullRequest

MOCK_OWNER = "acme"
MOCK_REPO = "platform"


class GitHubClient(Protocol):
    def list_pull_requests(
        self, owner: str, repo: str, state: str, max_results: int
    ) -> PullPage: ...

    def get_pr_diff_summary(self, owner: str, repo: str, number: int) -> PullRequest: ...

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> GitHubIssue: ...

    def add_comment(self, owner: str, repo: str, number: int, body: str) -> GitHubComment: ...


def _file(filename: str, status: str, additions: int, deletions: int, summary: str) -> DiffFile:
    return DiffFile(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        summary=summary,
    )


def _seed_pulls() -> list[PullRequest]:
    return [
        PullRequest(
            number=41,
            title="Spike an in-memory rate limiter",
            body="Closed after the spike showed a per-process window is enough for the demo.",
            state="closed",
            author="arpan",
            overview="Explored a sliding window limiter. The spike was closed without merging.",
            files=[_file("notes/rate-limit.md", "added", 20, 0, "Spike notes for the limiter")],
        ),
        PullRequest(
            number=42,
            title="Add structured audit logging for agent tools",
            body="Writes one JSON event per tool call and redacts token-like strings.",
            state="open",
            author="arpan",
            overview="Adds a structured audit log for agent tool calls, with redaction.",
            files=[
                _file("src/audit/log.py", "added", 86, 0, "JSON audit logger writing to stderr"),
                _file(
                    "src/audit/redact.py",
                    "added",
                    34,
                    0,
                    "Redacts token-like strings before they are logged",
                ),
                _file("tests/test_audit.py", "added", 40, 0, "Covers redaction and the log shape"),
            ],
        ),
        PullRequest(
            number=43,
            title="Reject SSO callbacks that are missing state",
            body=(
                "Compares the callback state to the stored nonce and returns 400 when it is absent."
            ),
            state="open",
            author="riley",
            overview="Requires state on the SSO callback and covers the missing-state regression.",
            files=[
                _file(
                    "src/auth/callback.py",
                    "modified",
                    22,
                    6,
                    "Requires state and compares it to the stored nonce",
                ),
                _file(
                    "tests/test_callback.py",
                    "modified",
                    18,
                    1,
                    "Adds the missing-state regression",
                ),
            ],
        ),
    ]


def _seed_issues() -> list[GitHubIssue]:
    return [
        GitHubIssue(
            number=7,
            title="Document the mock query syntax",
            body="Describe project:, status:, type:, and key: filters for the demo Jira store.",
            state="open",
            author="arpan",
        )
    ]


class MockGitHubClient:
    """In-memory acme/platform repository used by the demo and the unit tests."""

    def __init__(self) -> None:
        self._pulls = {pull.number: pull for pull in _seed_pulls()}
        self._issues = {issue.number: issue for issue in _seed_issues()}
        self._next_number = max([*self._pulls, *self._issues]) + 1
        self._comment_seq = 0
        self._lock = threading.Lock()

    def list_pull_requests(self, owner: str, repo: str, state: str, max_results: int) -> PullPage:
        self._require_repo(owner, repo)
        with self._lock:
            pulls = [
                pull
                for pull in self._pulls.values()
                if state == "all" or pull.state == state
            ]
        pulls.sort(key=lambda pull: pull.number)
        return PullPage(pull_requests=pulls[:max_results], total=len(pulls))

    def get_pr_diff_summary(self, owner: str, repo: str, number: int) -> PullRequest:
        self._require_repo(owner, repo)
        with self._lock:
            pull = self._pulls.get(number)
        if pull is None:
            raise NotFoundError(f"Pull request {owner}/{repo}#{number} was not found")
        return pull

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> GitHubIssue:
        self._require_repo(owner, repo)
        with self._lock:
            issue = GitHubIssue(
                number=self._next_number,
                title=title,
                body=body,
                state="open",
                author="agent",
            )
            self._next_number += 1
            self._issues[issue.number] = issue
            return issue

    def add_comment(self, owner: str, repo: str, number: int, body: str) -> GitHubComment:
        self._require_repo(owner, repo)
        with self._lock:
            target = self._pulls.get(number)
            comments = target.comments if target is not None else None
            if comments is None and number in self._issues:
                comments = self._issues[number].comments
            if comments is None:
                raise NotFoundError(f"Issue or pull request {owner}/{repo}#{number} was not found")
            self._comment_seq += 1
            comment = GitHubComment(id=str(self._comment_seq), body=body, author="agent")
            comments.append(comment)
            return comment

    def _require_repo(self, owner: str, repo: str) -> None:
        if owner.lower() != MOCK_OWNER or repo.lower() != MOCK_REPO:
            raise NotFoundError(f"Repository {owner}/{repo} was not found")


def _repo_path(owner: str, repo: str) -> str:
    return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"


def _login(payload: dict[str, object]) -> str:
    user = payload.get("user")
    if isinstance(user, dict) and user.get("login"):
        return str(user["login"])
    return "unknown"


class LiveGitHubClient:
    """Thin GitHub REST client. The token is sent as a bearer credential."""

    def __init__(self, token: str, transport: httpx2.BaseTransport | None = None) -> None:
        self._http = httpx2.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "jira-github-mcp-demo",
            },
            transport=transport,
            timeout=20.0,
        )

    def list_pull_requests(self, owner: str, repo: str, state: str, max_results: int) -> PullPage:
        payload = send_json(
            self._http,
            "GET",
            f"{_repo_path(owner, repo)}/pulls?state={quote(state, safe='')}&per_page={max_results}",
            not_found=f"Repository {owner}/{repo} was not found",
        )
        if not isinstance(payload, list):
            raise BackendError("GitHub pull list was not a list")
        pulls = [_pull_summary(item) for item in payload if isinstance(item, dict)]
        return PullPage(pull_requests=pulls, total=len(pulls))

    def get_pr_diff_summary(self, owner: str, repo: str, number: int) -> PullRequest:
        path = _repo_path(owner, repo)
        missing = f"Pull request {owner}/{repo}#{number} was not found"
        pull_payload = send_json(
            self._http, "GET", f"{path}/pulls/{number}", not_found=missing
        )
        files_payload = send_json(
            self._http, "GET", f"{path}/pulls/{number}/files", not_found=missing
        )
        if not isinstance(pull_payload, dict) or not isinstance(files_payload, list):
            raise BackendError("GitHub pull response had an unexpected shape")
        files = [_diff_file(item) for item in files_payload if isinstance(item, dict)]
        body = str(pull_payload.get("body") or "")
        return PullRequest(
            number=number,
            title=str(pull_payload.get("title") or ""),
            body=body,
            state=str(pull_payload.get("state") or "open"),
            author=_login(pull_payload),
            overview=body or f"{len(files)} files changed",
            files=files,
        )

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> GitHubIssue:
        payload = send_json(
            self._http,
            "POST",
            f"{_repo_path(owner, repo)}/issues",
            json_body={"title": title, "body": body},
            not_found=f"Repository {owner}/{repo} was not found",
        )
        if not isinstance(payload, dict) or "number" not in payload:
            raise BackendError("GitHub create-issue response is missing a number")
        return GitHubIssue(
            number=int(payload["number"]),
            title=str(payload.get("title") or title),
            body=str(payload.get("body") or body),
            state=str(payload.get("state") or "open"),
            author=_login(payload),
        )

    def add_comment(self, owner: str, repo: str, number: int, body: str) -> GitHubComment:
        payload = send_json(
            self._http,
            "POST",
            f"{_repo_path(owner, repo)}/issues/{number}/comments",
            json_body={"body": body},
            not_found=f"Issue or pull request {owner}/{repo}#{number} was not found",
        )
        if not isinstance(payload, dict) or "id" not in payload:
            raise BackendError("GitHub comment response is missing an id")
        return GitHubComment(id=str(payload["id"]), body=body, author=_login(payload))


def _pull_summary(payload: dict[str, object]) -> PullRequest:
    return PullRequest(
        number=int(payload["number"]),
        title=str(payload.get("title") or ""),
        body=str(payload.get("body") or ""),
        state=str(payload.get("state") or "open"),
        author=_login(payload),
        overview=str(payload.get("body") or ""),
    )


def _diff_file(payload: dict[str, object]) -> DiffFile:
    filename = str(payload.get("filename") or "")
    status = str(payload.get("status") or "modified")
    additions = int(payload.get("additions") or 0)
    deletions = int(payload.get("deletions") or 0)
    return DiffFile(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        summary=f"{status} {filename} (+{additions} -{deletions})",
    )
