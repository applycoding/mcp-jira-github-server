import json

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from jira_github_mcp.catalog import TOOL_NAMES
from jira_github_mcp.config import Settings
from jira_github_mcp.server import build_server


def test_server_registers_every_tool() -> None:
    server = build_server(Settings())
    tools = anyio.run(server.list_tools)
    assert {tool.name for tool in tools} == set(TOOL_NAMES)
    search = next(tool for tool in tools if tool.name == "jira_search_issues")
    assert search.annotations is not None
    assert search.annotations.read_only_hint is True


def test_server_hides_tools_outside_the_allowlist() -> None:
    server = build_server(Settings(tool_allowlist=("github_list_pull_requests",)))
    tools = anyio.run(server.list_tools)
    assert [tool.name for tool in tools] == ["github_list_pull_requests"]


def test_server_call_returns_json_text() -> None:
    server = build_server(Settings())
    result = anyio.run(server.call_tool, "jira_search_issues", {"query": "login"})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["issues"][0]["key"] == "PLAT-101"


def test_server_maps_read_only_to_a_tool_error() -> None:
    server = build_server(Settings(read_only=True))
    with pytest.raises(ToolError, match="read_only"):
        anyio.run(
            server.call_tool,
            "github_create_issue",
            {"owner": "acme", "repo": "platform", "title": "Nope"},
        )
