#!/usr/bin/env python3
"""Call the demo server the way an agent host would.

Install the package first (`pip install -e .`), then run:

    python examples/agent_example.py

The child process uses the mock backend in read-only mode, so this script
only searches Jira and reads a pull request.
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _text(result: object) -> str:
    if getattr(result, "is_error", False):
        raise SystemExit(_blocks(result) or "tool call failed")
    return _blocks(result)


def _blocks(result: object) -> str:
    chunks: list[str] = []
    for block in getattr(result, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "jira_github_mcp"],
        env={
            "MCP_BACKEND": "mock",
            "MCP_READ_ONLY": "true",
            "LOG_LEVEL": "WARNING",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = ", ".join(tool.name for tool in listed.tools)
            print(f"tools: {names}")
            print(_text(await session.call_tool("jira_search_issues", {"query": "login"})))
            print(
                _text(
                    await session.call_tool(
                        "github_get_pr_diff_summary",
                        {"owner": "acme", "repo": "platform", "number": 43},
                    )
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
