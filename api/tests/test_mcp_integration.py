import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.enums import ToolCategory
from api.services.workflow.pipecat_engine import PipecatEngine
from api.tests.pipecat_test_utils import stub_agent_runtime
from api.tests.support.mcp_mock_server import running_mcp_server


def _mcp_tool(url: str):
    t = MagicMock()
    t.tool_uuid = "uuid-" + uuid.uuid4().hex[:8]
    t.name = "Acme MCP"
    t.category = ToolCategory.MCP.value
    t.definition = {
        "schema_version": 1,
        "type": "mcp",
        "config": {"transport": "streamable_http", "url": url},
    }
    return t


@pytest.mark.asyncio
async def test_engine_opens_and_closes_mcp_sessions(monkeypatch):
    async with running_mcp_server() as base_url:
        tool = _mcp_tool(base_url)

        engine = PipecatEngine.__new__(PipecatEngine)
        engine._contact_phone = None
        engine._active_agent = stub_agent_runtime()
        engine._retired_agents = []
        node = MagicMock()
        node.tool_uuids = [tool.tool_uuid]
        workflow = MagicMock()
        workflow.nodes = {"n1": node}
        engine.active_agent.workflow = workflow
        engine.active_agent.mcp_sessions = {}

        from api.db import db_client

        monkeypatch.setattr(
            db_client, "get_tools_by_uuids", AsyncMock(return_value=[tool])
        )
        monkeypatch.setattr(
            db_client, "get_credential_by_uuid", AsyncMock(return_value=None)
        )
        engine._get_organization_id = AsyncMock(return_value=42)

        await engine._open_mcp_sessions()
        try:
            assert tool.tool_uuid in engine.active_agent.mcp_sessions
            sess = engine.active_agent.mcp_sessions[tool.tool_uuid]
            assert sess.available is True
            assert len(sess.function_schemas()) == 2
        finally:
            await engine.close_mcp_sessions()
        assert engine.active_agent.mcp_sessions == {}


@pytest.mark.asyncio
async def test_open_mcp_sessions_swallows_db_error(monkeypatch):
    engine = PipecatEngine.__new__(PipecatEngine)
    engine._contact_phone = None
    engine._active_agent = stub_agent_runtime()
    engine._retired_agents = []
    node = MagicMock()
    node.tool_uuids = ["uuid-deadbeef"]
    workflow = MagicMock()
    workflow.nodes = {"n1": node}
    engine.active_agent.workflow = workflow
    engine.active_agent.mcp_sessions = {}

    from api.db import db_client

    monkeypatch.setattr(
        db_client,
        "get_tools_by_uuids",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    engine._get_organization_id = AsyncMock(return_value=42)

    # Must NOT raise
    await engine._open_mcp_sessions()
    assert engine.active_agent.mcp_sessions == {}


@pytest.mark.asyncio
async def test_open_mcp_sessions_skips_tool_when_credential_fetch_fails(monkeypatch):
    tool = _mcp_tool("http://127.0.0.1:1/mcp")
    tool.definition["config"]["credential_uuid"] = "cred-1234"

    engine = PipecatEngine.__new__(PipecatEngine)
    engine._contact_phone = None
    engine._active_agent = stub_agent_runtime()
    engine._retired_agents = []
    node = MagicMock()
    node.tool_uuids = [tool.tool_uuid]
    workflow = MagicMock()
    workflow.nodes = {"n1": node}
    engine.active_agent.workflow = workflow
    engine.active_agent.mcp_sessions = {}

    from api.db import db_client

    monkeypatch.setattr(db_client, "get_tools_by_uuids", AsyncMock(return_value=[tool]))
    monkeypatch.setattr(
        db_client,
        "get_credential_by_uuid",
        AsyncMock(side_effect=RuntimeError("cred store down")),
    )
    engine._get_organization_id = AsyncMock(return_value=42)

    # Must NOT raise, and must skip the tool (no futile unauthenticated start)
    await engine._open_mcp_sessions()
    assert engine.active_agent.mcp_sessions == {}


def _engine_with(tool, context: dict, contact_phone: str | None) -> PipecatEngine:
    engine = PipecatEngine.__new__(PipecatEngine)
    engine._call_context_vars = context
    engine._contact_phone = contact_phone
    engine._active_agent = stub_agent_runtime()
    engine._retired_agents = []
    node = MagicMock()
    node.tool_uuids = [tool.tool_uuid]
    workflow = MagicMock()
    workflow.nodes = {"n1": node}
    engine.active_agent.workflow = workflow
    engine.active_agent.mcp_sessions = {}
    engine._get_organization_id = AsyncMock(return_value=42)
    return engine


CALLER = "+353871234567"
# What an editor's template variables, a public API call or a pre-call fetch
# response could put in the call context.
FORGED_CONTEXT = {
    "provider": "twilio",
    "direction": "inbound",
    "caller_number": "+353861111111",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tools_service", "contact_phone", "available"),
    [
        (True, CALLER, True),
        # Not the tools service: the number never leaves the API.
        (False, CALLER, False),
        # A web run or hidden number: forged context variables send nothing.
        (True, None, False),
    ],
)
async def test_only_the_tools_service_learns_the_snapshotted_number(
    monkeypatch, tools_service, contact_phone, available
):
    from api import constants
    from api.db import db_client
    from api.services.tool_integrations.call_context import CONTACT_PHONE_HEADER

    async with running_mcp_server(
        required_headers={CONTACT_PHONE_HEADER: CALLER}
    ) as base_url:
        origin = base_url.removesuffix("/mcp")
        monkeypatch.setattr(
            constants,
            "TOOLS_SERVICE_URL",
            origin if tools_service else "http://fallcha-tools:8000",
        )
        tool = _mcp_tool(base_url)
        monkeypatch.setattr(
            db_client, "get_tools_by_uuids", AsyncMock(return_value=[tool])
        )
        engine = _engine_with(tool, dict(FORGED_CONTEXT), contact_phone)

        await engine._open_mcp_sessions()
        try:
            session = engine.active_agent.mcp_sessions[tool.tool_uuid]
            # The mock server refuses requests without the caller's header,
            # so the forged caller_number was never sent either.
            assert session.available is available
        finally:
            await engine.close_mcp_sessions()
