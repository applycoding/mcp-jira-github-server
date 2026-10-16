"""Pydantic models for tool arguments. The service rejects anything outside these bounds."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_NAME = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
_REPO = r"^[A-Za-z0-9._-]{1,100}$"
_STATUS = r"^[A-Za-z][A-Za-z0-9 _-]{0,39}$"


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIssuesInput(ToolInput):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=10, ge=1, le=50)


class CreateJiraIssueInput(ToolInput):
    project: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    issue_type: Literal["Bug", "Task", "Story"] = "Task"


class AddJiraCommentInput(ToolInput):
    issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")
    body: str = Field(min_length=1, max_length=10000)


class TransitionIssueInput(ToolInput):
    issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")
    status: str = Field(pattern=_STATUS)


class ListPullRequestsInput(ToolInput):
    owner: str = Field(pattern=_NAME)
    repo: str = Field(pattern=_REPO)
    state: Literal["open", "closed", "all"] = "open"
    max_results: int = Field(default=10, ge=1, le=50)


class DiffSummaryInput(ToolInput):
    owner: str = Field(pattern=_NAME)
    repo: str = Field(pattern=_REPO)
    number: int = Field(ge=1)


class CreateGitHubIssueInput(ToolInput):
    owner: str = Field(pattern=_NAME)
    repo: str = Field(pattern=_REPO)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(default="", max_length=10000)


class AddGitHubCommentInput(ToolInput):
    owner: str = Field(pattern=_NAME)
    repo: str = Field(pattern=_REPO)
    number: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=10000)
