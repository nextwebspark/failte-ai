"""Agent skills runtime against a real database: the per-call preload is
org-scoped and active-only, and saving a workflow rejects skill UUIDs that
are not active skills of the saving organization."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.db import db_client
from api.db.models import OrganizationModel
from api.db.skill_client import SkillContent, SkillFile
from api.services.skills.runtime import load_skill_set
from api.services.workflow.tool_name_validation import (
    validate_workflow_tool_name_collisions,
)


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


async def _org(sessions) -> int:
    async with sessions() as session:
        organization = OrganizationModel(provider_id=f"skills-rt-{uuid.uuid4().hex}")
        session.add(organization)
        await session.commit()
        return int(organization.id)


async def _skill(org_id: int, name: str, files: tuple[SkillFile, ...] = ()):
    return await db_client.create_workspace_skill(
        organization_id=org_id,
        created_by=None,
        content=SkillContent(
            name=name, description=f"{name} desc", body_md=f"{name} body", files=files
        ),
        allowed_tool_uuids=None,
    )


@pytest.fixture
async def orgs(sessions):
    org_a, org_b = await _org(sessions), await _org(sessions)
    returns = await _skill(
        org_a,
        "returns-policy",
        (SkillFile(path="references/policy.md", content="30 days."),),
    )
    archived = await _skill(org_a, "old-skill")
    await db_client.archive_workspace_skill(org_a, archived.skill_uuid)
    private_b = await _skill(org_b, "b-private")
    return SimpleNamespace(
        a=org_a, b=org_b, returns=returns, archived=archived, private_b=private_b
    )


@pytest.mark.asyncio
async def test_preload_is_org_scoped_and_active_only(orgs) -> None:
    skill_set = await load_skill_set(db_client, orgs.a)
    assert [s.name for s in skill_set.skills] == ["returns-policy"]
    [returns] = skill_set.skills
    assert returns.skill_uuid == orgs.returns.skill_uuid
    policy = returns.file("references/policy.md")
    assert policy is not None and policy.content == "30 days."
    # Another org's private skill is never preloaded, even when named.
    node = skill_set.for_node([orgs.private_b.skill_uuid])
    assert node.is_empty

    other = await load_skill_set(db_client, orgs.b)
    assert [s.name for s in other.skills] == ["b-private"]


def _workflow(**data) -> dict:
    return {
        "nodes": [
            {
                "id": "n1",
                "type": "agentNode",
                "position": {"x": 0, "y": 0},
                "data": {"name": "Help", "prompt": "Help.", **data},
            }
        ],
        "edges": [],
    }


@pytest.mark.asyncio
async def test_save_validation_rejects_unknown_and_foreign_but_not_archived(
    orgs,
) -> None:
    ok = await validate_workflow_tool_name_collisions(
        _workflow(
            skill_uuids=[orgs.returns.skill_uuid],
            preload_skill_uuids=[orgs.archived.skill_uuid],
        ),
        orgs.a,
    )
    assert ok == []

    unknown = str(uuid.uuid4())
    errors = await validate_workflow_tool_name_collisions(
        _workflow(
            skill_uuids=[orgs.returns.skill_uuid, orgs.private_b.skill_uuid],
            preload_skill_uuids=[unknown, orgs.archived.skill_uuid],
        ),
        orgs.a,
    )
    by_field = {e["field"]: e["message"] for e in errors}
    assert set(by_field) == {"data.skill_uuids", "data.preload_skill_uuids"}
    assert orgs.private_b.skill_uuid in by_field["data.skill_uuids"]
    assert orgs.returns.skill_uuid not in by_field["data.skill_uuids"]
    assert unknown in by_field["data.preload_skill_uuids"]
    assert orgs.archived.skill_uuid not in by_field["data.preload_skill_uuids"]


@pytest.mark.asyncio
async def test_active_skill_cap(orgs, monkeypatch) -> None:
    from api.errors.skills import SkillLimitError
    from api.services.skills import get_skill_service, validation

    service = get_skill_service()
    monkeypatch.setattr(validation, "MAX_ACTIVE_SKILLS", 2)
    content = SkillContent(name="second", description="d", body_md="b")
    await service.create_skill(orgs.a, created_by=None, content=content)
    with pytest.raises(SkillLimitError) as exc:
        await service.create_skill(
            orgs.a,
            created_by=None,
            content=SkillContent(name="third", description="d", body_md="b"),
        )
    assert exc.value.status_code == 409
    # Archived skills do not count.
    await db_client.archive_workspace_skill(orgs.a, orgs.returns.skill_uuid)
    await service.create_skill(
        orgs.a,
        created_by=None,
        content=SkillContent(name="third", description="d", body_md="b"),
    )
