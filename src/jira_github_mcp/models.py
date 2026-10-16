"""Records returned by the Jira and GitHub backends."""

from __future__ import annotations

from dataclasses import dataclass, field


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


@dataclass(slots=True)
class JiraComment:
    id: str
    body: str
    author: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "body": self.body, "author": self.author}


@dataclass(slots=True)
class JiraIssue:
    key: str
    project: str
    summary: str
    description: str
    issue_type: str
    status: str
    comments: list[JiraComment] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "project": self.project,
            "summary": self.summary,
            "description": clip(self.description, 2000),
            "issue_type": self.issue_type,
            "status": self.status,
            "comment_count": len(self.comments),
        }


@dataclass(slots=True)
class IssuePage:
    issues: list[JiraIssue]
    total: int


@dataclass(slots=True)
class DiffFile:
    filename: str
    status: str
    additions: int
    deletions: int
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "summary": self.summary,
        }


@dataclass(slots=True)
class GitHubComment:
    id: str
    body: str
    author: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "body": self.body, "author": self.author}


@dataclass(slots=True)
class PullRequest:
    number: int
    title: str
    body: str
    state: str
    author: str
    overview: str
    files: list[DiffFile] = field(default_factory=list)
    comments: list[GitHubComment] = field(default_factory=list)

    def to_summary(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "author": self.author,
            "body": clip(self.body, 500),
        }

    def diff_summary(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "overview": clip(self.overview or self.body, 1000),
            "files_changed": len(self.files),
            "additions": sum(item.additions for item in self.files),
            "deletions": sum(item.deletions for item in self.files),
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(slots=True)
class PullPage:
    pull_requests: list[PullRequest]
    total: int


@dataclass(slots=True)
class GitHubIssue:
    number: int
    title: str
    body: str
    state: str
    author: str
    comments: list[GitHubComment] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "body": clip(self.body, 2000),
            "state": self.state,
            "author": self.author,
            "comment_count": len(self.comments),
        }
