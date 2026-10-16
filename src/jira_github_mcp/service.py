"""Tool dispatch: validate input, apply guardrails, then call a backend."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, assert_never, cast

from pydantic import ValidationError

from jira_github_mcp.backends import build_clients
from jira_github_mcp.backends.github import GitHubClient
from jira_github_mcp.backends.jira import JiraClient
from jira_github_mcp.catalog import TOOL_NAMES, WRITE_TOOLS, ToolName
from jira_github_mcp.config import Settings
from jira_github_mcp.errors import BackendError, ConflictError, NotFoundError, ToolFailure
from jira_github_mcp.inputs import (
    AddGitHubCommentInput,
    AddJiraCommentInput,
    CreateGitHubIssueInput,
    CreateJiraIssueInput,
    DiffSummaryInput,
    ListPullRequestsInput,
    SearchIssuesInput,
    TransitionIssueInput,
)
from jira_github_mcp.rate_limit import RateLimiter, RateLimitExceeded
from jira_github_mcp.structured_log import log_event

_INPUTS = {
    "jira_search_issues": SearchIssuesInput,
    "jira_create_issue": CreateJiraIssueInput,
    "jira_add_comment": AddJiraCommentInput,
    "jira_transition_issue": TransitionIssueInput,
    "github_list_pull_requests": ListPullRequestsInput,
    "github_get_pr_diff_summary": DiffSummaryInput,
    "github_create_issue": CreateGitHubIssueInput,
    "github_add_comment": AddGitHubCommentInput,
}


class ToolService:
    def __init__(
        self,
        settings: Settings,
        jira: JiraClient,
        github: GitHubClient,
        rate_limiter: RateLimiter,
    ) -> None:
        self.settings = settings
        self.jira = jira
        self.github = github
        self.rate_limiter = rate_limiter

    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = self._call(name, arguments)
        except ToolFailure as exc:
            self._log(name, started, ok=False, code=exc.code)
            raise
        except NotFoundError as exc:
            failure = ToolFailure("not_found", str(exc))
            self._log(name, started, ok=False, code=failure.code)
            raise failure from exc
        except ConflictError as exc:
            failure = ToolFailure("conflict", str(exc))
            self._log(name, started, ok=False, code=failure.code)
            raise failure from exc
        except BackendError as exc:
            failure = ToolFailure("backend_error", str(exc))
            self._log(name, started, ok=False, code=failure.code)
            raise failure from exc
        self._log(name, started, ok=True, code="")
        return result

    def _call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise ToolFailure("unknown_tool", f"Unknown tool: {name}")
        if self.settings.tool_allowlist and name not in self.settings.tool_allowlist:
            raise ToolFailure("not_allowed", f"{name} is not on the tool allowlist")
        if self.settings.read_only and name in WRITE_TOOLS:
            raise ToolFailure("read_only", f"{name} is disabled while MCP_READ_ONLY is true")
        data = self._validate(name, arguments)
        self._check_scope(data)
        try:
            self.rate_limiter.check(name)
        except RateLimitExceeded as exc:
            raise ToolFailure("rate_limited", str(exc)) from exc
        return self._dispatch(cast(ToolName, name), data)

    def _validate(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        model = _INPUTS[name]
        try:
            parsed = model.model_validate(dict(arguments))
        except ValidationError as exc:
            messages = []
            for err in exc.errors():
                location = ".".join(str(part) for part in err["loc"])
                messages.append(f"{location}: {err['msg']}")
            summary = "; ".join(messages)
            raise ToolFailure("invalid_input", summary) from exc
        return parsed.model_dump()

    def _check_scope(self, data: dict[str, Any]) -> None:
        if "project" in data:
            self._require_project(str(data["project"]))
        if "issue_key" in data:
            self._require_project(str(data["issue_key"]).split("-", 1)[0])
        if "owner" in data and "repo" in data:
            self._require_repo(str(data["owner"]), str(data["repo"]))

    def _require_project(self, project: str) -> None:
        allowed = self.settings.jira_project_allowlist
        if allowed and project not in allowed:
            raise ToolFailure("not_allowed", f"Jira project {project} is not on the allowlist")

    def _require_repo(self, owner: str, repo: str) -> None:
        allowed = self.settings.github_repo_allowlist
        if allowed and f"{owner}/{repo}".lower() not in allowed:
            raise ToolFailure("not_allowed", f"Repository {owner}/{repo} is not on the allowlist")

    def _dispatch(self, name: ToolName, data: dict[str, Any]) -> dict[str, Any]:
        match name:
            case "jira_search_issues":
                return self._search_issues(data)
            case "jira_create_issue":
                return self.jira.create_issue(
                    data["project"], data["summary"], data["description"], data["issue_type"]
                ).to_dict()
            case "jira_add_comment":
                comment = self.jira.add_comment(data["issue_key"], data["body"])
                return {"issue_key": data["issue_key"], "comment": comment.to_dict()}
            case "jira_transition_issue":
                return self.jira.transition_issue(data["issue_key"], data["status"]).to_dict()
            case "github_list_pull_requests":
                return self._list_pulls(data)
            case "github_get_pr_diff_summary":
                pull = self.github.get_pr_diff_summary(data["owner"], data["repo"], data["number"])
                return pull.diff_summary()
            case "github_create_issue":
                return self.github.create_issue(
                    data["owner"], data["repo"], data["title"], data["body"]
                ).to_dict()
            case "github_add_comment":
                comment = self.github.add_comment(
                    data["owner"], data["repo"], data["number"], data["body"]
                )
                return {"number": data["number"], "comment": comment.to_dict()}
            case _:
                assert_never(name)

    def _search_issues(self, data: dict[str, Any]) -> dict[str, Any]:
        page = self.jira.search_issues(
            data["query"], data["max_results"], self.settings.jira_project_allowlist
        )
        allowed = self.settings.jira_project_allowlist
        visible = [issue for issue in page.issues if not allowed or issue.project in allowed]
        total = page.total if len(visible) == len(page.issues) else len(visible)
        return {"issues": [issue.to_dict() for issue in visible], "total": total}

    def _list_pulls(self, data: dict[str, Any]) -> dict[str, Any]:
        page = self.github.list_pull_requests(
            data["owner"], data["repo"], data["state"], data["max_results"]
        )
        return {
            "pull_requests": [pull.to_summary() for pull in page.pull_requests],
            "total": page.total,
        }

    def _log(self, tool: str, started: float, *, ok: bool, code: str) -> None:
        # Argument values stay out of the log. They can contain issue text or secrets.
        log_event(
            logging.INFO if ok else logging.WARNING,
            "tool_call",
            tool=tool,
            ok=ok,
            code=code,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def build_service(
    settings: Settings,
    jira: JiraClient | None = None,
    github: GitHubClient | None = None,
    rate_limiter: RateLimiter | None = None,
) -> ToolService:
    if jira is None or github is None:
        built_jira, built_github = build_clients(settings)
        jira = built_jira if jira is None else jira
        github = built_github if github is None else github
    limiter = rate_limiter or RateLimiter(settings.rate_limit_per_minute)
    return ToolService(settings, jira, github, limiter)
