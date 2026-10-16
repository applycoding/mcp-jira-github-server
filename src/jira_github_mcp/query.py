"""Shared query language for the mock store and the live Jira JQL builder.

Mock filters use `project:PLAT`, `status:"In Progress"`, `type:Bug`, and `key:PLAT-101`.
Any remaining words are a case-insensitive AND search. A string that already looks
like JQL is sent to Jira unchanged.
"""

from __future__ import annotations

import re

_FIELD = re.compile(r"\b(project|status|type|key):(?:\"([^\"]*)\"|(\S+))", re.IGNORECASE)
_JQL = re.compile(r"=|~|\bORDER\s+BY\b|\bIN\s*\(", re.IGNORECASE)


def looks_like_jql(query: str) -> bool:
    return _JQL.search(query) is not None


def parse_query(query: str) -> tuple[dict[str, str], str]:
    filters: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        value = match.group(2) if match.group(2) is not None else match.group(3)
        filters[match.group(1).lower()] = value
        return " "

    text = " ".join(_FIELD.sub(replace, query).split())
    return filters, text


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def to_jql(query: str, projects: tuple[str, ...]) -> str:
    """Translate a demo query into JQL. Raw JQL is returned unchanged."""
    if looks_like_jql(query):
        return query
    filters, text = parse_query(query)
    clauses: list[str] = []
    if projects and "project" not in filters:
        if len(projects) == 1:
            clauses.append(f"project = {projects[0]}")
        else:
            clauses.append("project in (" + ", ".join(projects) + ")")
    if "project" in filters:
        clauses.append(f"project = {filters['project'].upper()}")
    if "status" in filters:
        clauses.append(f"status = {_quote(filters['status'])}")
    if "type" in filters:
        clauses.append(f"issuetype = {_quote(filters['type'])}")
    if "key" in filters:
        clauses.append(f"key = {filters['key'].upper()}")
    if text:
        clauses.append(f"text ~ {_quote(text)}")
    if not clauses:
        clauses.append("text ~ " + _quote(query))
    return " AND ".join(clauses) + " ORDER BY updated DESC"
