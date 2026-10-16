"""Small HTTP helper for the live Jira and GitHub clients."""

from __future__ import annotations

from typing import Any

import httpx2

from jira_github_mcp.errors import BackendError, NotFoundError


def send_json(
    client: httpx2.Client,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    not_found: str,
) -> Any:
    options: dict[str, Any] = {}
    if json_body is not None:
        options["json"] = json_body
    try:
        response = client.request(method, url, **options)
    except httpx2.HTTPError as exc:
        raise BackendError(f"{method} {url} failed ({exc.__class__.__name__})") from exc
    if response.status_code == 404:
        raise NotFoundError(not_found)
    if response.status_code >= 400:
        detail = " ".join(response.text.split())[:240]
        raise BackendError(f"{method} {url} returned HTTP {response.status_code}: {detail}")
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise BackendError(f"{method} {url} returned a non-JSON body") from exc
