"""MCP discovery tool for agent skills (fork-owned).

Node properties of type `skill_refs` (`skill_uuids`, `preload_skill_uuids`)
carry skill UUIDs that resolve against this catalog.
"""

from api.db import db_client
from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool


@traced_tool
async def list_skills() -> list[dict]:
    """List the workspace's active agent skills.

    Returns each skill's `skill_uuid` (use this in node `skill_uuids` and
    `preload_skill_uuids` properties), `name` and `description`. Every
    active skill is offered on every node unless the node narrows the list
    with `skill_uuids`.
    """
    user = await authenticate_mcp_request()
    skills = await db_client.list_workspace_skills(user.selected_organization_id)
    return [
        {
            "skill_uuid": s.skill_uuid,
            "name": s.content.name,
            "description": s.content.description,
        }
        for s in skills
    ]
