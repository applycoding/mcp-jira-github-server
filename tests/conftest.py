import pytest

from jira_github_mcp.config import Settings
from jira_github_mcp.service import ToolService, build_service


@pytest.fixture
def service() -> ToolService:
    return build_service(Settings())
