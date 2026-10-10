"""Skills API against a real database: library (platform admin), workspace
skills, copy-on-select, update detection, import/export, tenant isolation
and role enforcement."""

import importlib.util
import io
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import Header
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app import app
from api.db import db_client
from api.db.models import OrganizationModel, UserModel
from api.enums import OrgRole, ToolStatus
from api.services.auth.depends import get_user
from api.services.skills import LibraryService
from api.services.skills.archive import export_skill_zip
from api.services.skills.seeds import load_seeds

pytestmark = pytest.mark.real_org_roles

SKILLS = "/api/v1/skills"
LIBRARY = "/api/v1/skill-library"

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "ea7d85c1bebb_saas_add_agent_skills.py"
)


# -- fixtures --------------------------------------------------------------------


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


async def _org(sessions, roles, *, superuser_admin: bool = False) -> SimpleNamespace:
    async with sessions() as session:
        organization = OrganizationModel(provider_id=f"skills-{uuid.uuid4().hex}")
        session.add(organization)
        await session.commit()
    members = {}
    for role in roles:
        async with sessions() as session:
            user = UserModel(
                provider_id=f"skills-{uuid.uuid4().hex}",
                email=f"{role}-{uuid.uuid4().hex}@example.com",
                selected_organization_id=organization.id,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
        await db_client.add_user_to_organization(user.id, organization.id, role=role)
        members[role] = user
    superuser = None
    if superuser_admin:
        async with sessions() as session:
            superuser = UserModel(
                provider_id=f"skills-su-{uuid.uuid4().hex}",
                email=f"su-{uuid.uuid4().hex}@example.com",
                selected_organization_id=organization.id,
                is_superuser=True,
            )
            session.add(superuser)
            await session.commit()
        await db_client.add_user_to_organization(
            superuser.id, organization.id, role=OrgRole.VIEWER
        )
    return SimpleNamespace(id=organization.id, members=members, superuser=superuser)


@pytest.fixture
async def org(sessions):
    return await _org(sessions, tuple(OrgRole), superuser_admin=True)


@pytest.fixture
async def other_org(sessions):
    return await _org(sessions, (OrgRole.ADMIN,))


@pytest.fixture
async def client(sessions):
    """``client(user)`` -> an HTTP client authenticated as ``user``; clients
    for different users can be used side by side."""

    async def _user(x_test_user: Annotated[str, Header()]):
        async with db_client.async_session() as session:
            return await session.scalar(
                select(UserModel).where(UserModel.id == int(x_test_user))
            )

    app.dependency_overrides[get_user] = _user
    clients: dict[int, AsyncClient] = {}

    def as_user(user: UserModel) -> AsyncClient:
        if user.id not in clients:
            clients[user.id] = AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers={"X-Test-User": str(user.id)},
            )
        return clients[user.id]

    yield as_user
    for http in clients.values():
        await http.aclose()
    app.dependency_overrides.pop(get_user, None)


def _name(prefix: str = "skill") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _skill_body(name: str, **extra) -> dict:
    body = {
        "name": name,
        "description": "Answer questions about returns.",
        "body_md": "# Returns\n\nline one\nline two",
        "files": [{"path": "references/policy.md", "content": "30 days."}],
    }
    body.update(extra)
    return body


async def _published_library_skill(http, superuser) -> dict:
    name = _name("lib")
    response = await http(superuser).post(
        LIBRARY,
        json=_skill_body(
            name, category="support", frontmatter_extra={"license": "MIT"}
        ),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["status"], created["version"]) == ("draft", 0)
    published = await http(superuser).post(
        f"{LIBRARY}/{created['library_skill_uuid']}/publish"
    )
    assert published.status_code == 200
    assert (published.json()["status"], published.json()["version"]) == (
        "published",
        1,
    )
    return published.json()


async def _create_tool(org_id: int, user_id: int, status: ToolStatus | None = None):
    tool = await db_client.create_tool(
        organization_id=org_id,
        user_id=user_id,
        name=f"tool-{uuid.uuid4().hex[:6]}",
        definition={"schema_version": 1, "type": "http_api", "config": {}},
    )
    if status is not None:
        await db_client.update_tool(tool.tool_uuid, org_id, status=status.value)
    return tool.tool_uuid


# -- library ---------------------------------------------------------------------------


async def test_library_writes_need_a_platform_admin(client, org):
    lib = await _published_library_skill(client, org.superuser)
    uuid_ = lib["library_skill_uuid"]
    for role, user in org.members.items():
        http = client(user)
        calls = [
            http.post(LIBRARY, json=_skill_body(_name())),
            http.patch(f"{LIBRARY}/{uuid_}", json={"body_md": "x"}),
            http.post(f"{LIBRARY}/{uuid_}/publish"),
            http.post(f"{LIBRARY}/{uuid_}/deprecate"),
            http.delete(f"{LIBRARY}/{uuid_}"),
            http.post(f"{LIBRARY}/sync-seeds"),
        ]
        for call in calls:
            response = await call
            assert response.status_code == 403, (role, response.text)
        # Every member can read the published library.
        listed = await http.get(LIBRARY)
        assert listed.status_code == 200
        assert uuid_ in {s["library_skill_uuid"] for s in listed.json()["skills"]}
        detail = await http.get(f"{LIBRARY}/{uuid_}")
        assert detail.status_code == 200
        assert detail.json()["files"] == [
            {"path": "references/policy.md", "content": "30 days."}
        ]


async def test_library_lifecycle_and_versions(client, org):
    su = client(org.superuser)
    created = await su.post(LIBRARY, json=_skill_body(_name("lib")))
    uuid_ = created.json()["library_skill_uuid"]
    viewer = org.members[OrgRole.VIEWER]

    # Drafts are hidden from members but visible to platform admins.
    assert (await client(viewer).get(f"{LIBRARY}/{uuid_}")).status_code == 404
    assert uuid_ not in {
        s["library_skill_uuid"]
        for s in (await client(viewer).get(LIBRARY)).json()["skills"]
    }
    assert (await su.get(f"{LIBRARY}/{uuid_}")).status_code == 200
    developer = client(org.members[OrgRole.DEVELOPER])
    assert (await developer.post(f"{SKILLS}/from-library/{uuid_}")).status_code == 404

    # Editing a draft does not bump; publishing does; editing a published
    # skill's content bumps; renaming or recategorizing does not.
    assert (await su.patch(f"{LIBRARY}/{uuid_}", json={"body_md": "v0"})).json()[
        "version"
    ] == 0
    assert (await su.post(f"{LIBRARY}/{uuid_}/publish")).json()["version"] == 1
    assert (await su.post(f"{LIBRARY}/{uuid_}/publish")).json()["version"] == 1
    assert (await su.patch(f"{LIBRARY}/{uuid_}", json={"body_md": "v2"})).json()[
        "version"
    ] == 2
    renamed = await su.patch(
        f"{LIBRARY}/{uuid_}", json={"name": _name("ren"), "category": None}
    )
    assert renamed.json()["version"] == 2
    assert renamed.json()["category"] is None
    invalid = await su.patch(f"{LIBRARY}/{uuid_}", json={"name": "Bad Name"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "skill_invalid"

    deprecated = await su.post(f"{LIBRARY}/{uuid_}/deprecate")
    assert deprecated.json()["status"] == "deprecated"
    assert (await client(viewer).get(f"{LIBRARY}/{uuid_}")).status_code == 404
    assert (await developer.post(f"{SKILLS}/from-library/{uuid_}")).status_code == 404

    assert (await su.delete(f"{LIBRARY}/{uuid_}")).status_code == 204
    assert (await su.get(f"{LIBRARY}/{uuid_}")).status_code == 404


async def test_library_name_conflict(client, org):
    su = client(org.superuser)
    name = _name("lib")
    assert (await su.post(LIBRARY, json=_skill_body(name))).status_code == 201
    conflict = await su.post(LIBRARY, json=_skill_body(name))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "skill_name_conflict"


async def test_seed_sync_is_idempotent_and_bumps_on_change(sessions, tmp_path):
    name = _name("seed")
    folder = tmp_path / name
    (folder / "references").mkdir(parents=True)
    skill_md = folder / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: Seeded.\nmetadata:\n  category: demo\n---\n\nv1\n"
    )
    (folder / "references" / "a.md").write_text("ref")
    service = LibraryService(library=db_client)

    report = await service.sync_seeds(load_seeds(tmp_path))
    assert report.created == (name,)
    skills = {
        s.content.name: s for s in await service.list_skills(include_unpublished=True)
    }
    seeded = skills[name]
    assert (seeded.version, seeded.status.value, seeded.category) == (
        1,
        "published",
        "demo",
    )
    assert seeded.is_seeded

    again = await service.sync_seeds(load_seeds(tmp_path))
    assert again.unchanged == (name,) and not again.updated
    unchanged = await service.get_skill(
        seeded.library_skill_uuid, include_unpublished=True
    )
    assert unchanged.version == 1

    skill_md.write_text(skill_md.read_text().replace("v1", "v2"))
    changed = await service.sync_seeds(load_seeds(tmp_path))
    assert changed.updated == (name,)
    bumped = await service.get_skill(
        seeded.library_skill_uuid, include_unpublished=True
    )
    assert (bumped.version, bumped.content.body_md) == (2, "v2")
    assert [f.path for f in bumped.content.files] == ["references/a.md"]

    # A library skill authored through the API is never overwritten by a seed.
    from api.db.skill_client import SkillContent

    authored = _name("authored")
    await service.create_skill(
        SkillContent(name=authored, description="Mine.", body_md="mine")
    )
    clash = tmp_path / authored
    clash.mkdir()
    (clash / "SKILL.md").write_text(
        f"---\nname: {authored}\ndescription: Seed.\n---\nseed"
    )
    skipped = await service.sync_seeds(load_seeds(tmp_path))
    assert skipped.skipped == (authored,)


# -- workspace skills --------------------------------------------------------------------


async def test_crud_archive_and_name_reuse(client, org):
    dev = client(org.members[OrgRole.DEVELOPER])
    name = _name()
    created = await dev.post(SKILLS, json=_skill_body(name))
    assert created.status_code == 201, created.text
    skill = created.json()
    assert skill["source_library_uuid"] is None and skill["is_modified"] is False
    assert skill["files"] == [{"path": "references/policy.md", "content": "30 days."}]
    assert skill["created_by"] == org.members[OrgRole.DEVELOPER].id

    conflict = await dev.post(SKILLS, json=_skill_body(name))
    assert conflict.status_code == 409
    assert conflict.json()["suggested_name"] == f"{name}-2"

    edited = await dev.patch(
        f"{SKILLS}/{skill['skill_uuid']}",
        json={"body_md": "new body", "files": []},
    )
    assert edited.status_code == 200
    assert (edited.json()["body_md"], edited.json()["files"]) == ("new body", [])
    # A private skill is never "modified": there is nothing to diverge from.
    assert edited.json()["is_modified"] is False

    assert (await dev.delete(f"{SKILLS}/{skill['skill_uuid']}")).status_code == 204
    assert (await dev.delete(f"{SKILLS}/{skill['skill_uuid']}")).status_code == 404
    assert (
        await dev.patch(f"{SKILLS}/{skill['skill_uuid']}", json={"body_md": "x"})
    ).status_code == 404
    listed = (await dev.get(SKILLS)).json()["skills"]
    assert skill["skill_uuid"] not in {s["skill_uuid"] for s in listed}
    with_archived = (await dev.get(SKILLS, params={"include_archived": True})).json()
    assert {s["skill_uuid"]: s["status"] for s in with_archived["skills"]}[
        skill["skill_uuid"]
    ] == "archived"
    # Archived skills stay readable.
    assert (await dev.get(f"{SKILLS}/{skill['skill_uuid']}")).json()[
        "status"
    ] == "archived"

    # Archiving freed the name.
    assert (await dev.post(SKILLS, json=_skill_body(name))).status_code == 201


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"name": "Not Kebab"}, "Invalid skill name"),
        ({"description": ""}, "description"),
        ({"body_md": "  "}, "body"),
        ({"files": [{"path": "../x.md", "content": "x"}]}, "'..'"),
        ({"files": [{"path": "SKILL.md", "content": "x"}]}, "body_md"),
        ({"frontmatter_extra": {"compatibility": "x" * 501}}, "compatibility"),
    ],
)
async def test_create_validation_errors(client, org, override, fragment):
    response = await client(org.members[OrgRole.ADMIN]).post(
        SKILLS, json=_skill_body(_name()) | override
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "skill_invalid"
    assert fragment in response.json()["detail"]


async def test_copy_on_select_update_detection_diff_and_apply(client, org):
    su = client(org.superuser)
    dev = client(org.members[OrgRole.DEVELOPER])
    lib = await _published_library_skill(client, org.superuser)
    lib_uuid = lib["library_skill_uuid"]

    copied = await dev.post(f"{SKILLS}/from-library/{lib_uuid}")
    assert copied.status_code == 201, copied.text
    copy = copied.json()
    assert copy["name"] == lib["name"]
    assert (copy["source_library_uuid"], copy["source_version"]) == (lib_uuid, 1)
    assert copy["is_modified"] is False and copy["update_available"] is False
    assert copy["files"] == [{"path": "references/policy.md", "content": "30 days."}]
    assert copy["frontmatter_extra"]["license"] == "MIT"

    # Copying again collides; the 409 suggests a free name, which works.
    again = await dev.post(f"{SKILLS}/from-library/{lib_uuid}")
    assert again.status_code == 409
    suggestion = again.json()["suggested_name"]
    assert suggestion == f"{lib['name']}-2"
    second = await dev.post(
        f"{SKILLS}/from-library/{lib_uuid}", json={"name": suggestion}
    )
    assert second.status_code == 201

    # The library publishes v2: both copies see an update.
    await su.patch(
        f"{LIBRARY}/{lib_uuid}",
        json={
            "body_md": "# Returns\n\nline one\nline 2 changed",
            "files": [
                {"path": "references/policy.md", "content": "60 days."},
                {"path": "references/new.md", "content": "new"},
            ],
        },
    )
    fetched = (await dev.get(f"{SKILLS}/{copy['skill_uuid']}")).json()
    assert fetched["update_available"] is True
    listed = {s["skill_uuid"]: s for s in (await dev.get(SKILLS)).json()["skills"]}
    assert listed[copy["skill_uuid"]]["update_available"] is True

    diff = (await dev.get(f"{SKILLS}/{copy['skill_uuid']}/library-diff")).json()
    assert (diff["source_version"], diff["latest_version"]) == (1, 2)
    assert diff["update_available"] is True
    assert "-line two" in diff["diff"] and "+line 2 changed" in diff["diff"]
    assert "-30 days." in diff["diff"] and "+60 days." in diff["diff"]
    assert "+++ b/references/new.md" in diff["diff"]

    # Unmodified: one-click update.
    applied = await dev.post(
        f"{SKILLS}/{copy['skill_uuid']}/apply-library-update",
        json={"strategy": "replace"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["body_md"].endswith("line 2 changed")
    assert [f["path"] for f in body["files"]] == [
        "references/new.md",
        "references/policy.md",
    ]
    assert (body["source_version"], body["update_available"]) == (2, False)
    assert body["name"] == lib["name"]
    no_diff = (await dev.get(f"{SKILLS}/{copy['skill_uuid']}/library-diff")).json()
    assert no_diff["diff"] == ""

    # Renaming is a workspace setting, not a content change.
    renamed = await dev.patch(
        f"{SKILLS}/{second.json()['skill_uuid']}", json={"name": _name("renamed")}
    )
    assert renamed.json()["is_modified"] is False

    # Editing content marks the copy modified; an update then needs force.
    modified = await dev.patch(
        f"{SKILLS}/{copy['skill_uuid']}", json={"body_md": "my own version"}
    )
    assert modified.json()["is_modified"] is True
    # An edit that changes nothing does not count.
    same = await dev.patch(
        f"{SKILLS}/{second.json()['skill_uuid']}",
        json={"description": second.json()["description"]},
    )
    assert same.json()["is_modified"] is False

    await su.patch(f"{LIBRARY}/{lib_uuid}", json={"body_md": "v3 body"})
    refused = await dev.post(
        f"{SKILLS}/{copy['skill_uuid']}/apply-library-update", json={}
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "skill_state_conflict"
    forced = await dev.post(
        f"{SKILLS}/{copy['skill_uuid']}/apply-library-update", json={"force": True}
    )
    assert forced.status_code == 200
    assert (forced.json()["body_md"], forced.json()["is_modified"]) == (
        "v3 body",
        False,
    )
    assert forced.json()["source_version"] == 3

    # A deprecated library skill offers no update.
    await su.patch(f"{LIBRARY}/{lib_uuid}", json={"body_md": "v4"})
    await su.post(f"{LIBRARY}/{lib_uuid}/deprecate")
    after = (await dev.get(f"{SKILLS}/{copy['skill_uuid']}")).json()
    assert after["update_available"] is False
    assert (
        await dev.post(f"{SKILLS}/{copy['skill_uuid']}/apply-library-update", json={})
    ).status_code == 409

    # Deleting the library skill unlinks copies but keeps their content.
    await su.delete(f"{LIBRARY}/{lib_uuid}")
    orphan = (await dev.get(f"{SKILLS}/{copy['skill_uuid']}")).json()
    assert orphan["source_library_uuid"] is None
    assert orphan["body_md"] == "v3 body"


async def test_private_skill_has_no_library_diff(client, org):
    dev = client(org.members[OrgRole.DEVELOPER])
    skill = (await dev.post(SKILLS, json=_skill_body(_name()))).json()
    response = await dev.get(f"{SKILLS}/{skill['skill_uuid']}/library-diff")
    assert response.status_code == 409


async def test_cross_org_isolation(client, org, other_org):
    a_dev = client(org.members[OrgRole.DEVELOPER])
    name = _name("private")
    skill = (await a_dev.post(SKILLS, json=_skill_body(name))).json()
    skill_uuid = skill["skill_uuid"]

    b = client(other_org.members[OrgRole.ADMIN])
    assert skill_uuid not in {
        s["skill_uuid"] for s in (await b.get(SKILLS)).json()["skills"]
    }
    assert (await b.get(f"{SKILLS}/{skill_uuid}")).status_code == 404
    assert (
        await b.patch(f"{SKILLS}/{skill_uuid}", json={"body_md": "x"})
    ).status_code == 404
    assert (await b.delete(f"{SKILLS}/{skill_uuid}")).status_code == 404
    assert (await b.get(f"{SKILLS}/{skill_uuid}/export")).status_code == 404
    assert (await b.get(f"{SKILLS}/{skill_uuid}/library-diff")).status_code == 404
    assert (
        await b.post(f"{SKILLS}/{skill_uuid}/apply-library-update", json={})
    ).status_code == 404
    # A workspace skill uuid is not a library uuid: nothing to copy.
    assert (await b.post(f"{SKILLS}/from-library/{skill_uuid}")).status_code == 404
    # Names are per organization.
    assert (await b.post(SKILLS, json=_skill_body(name))).status_code == 201
    # A's skill is untouched.
    assert (await a_dev.get(f"{SKILLS}/{skill_uuid}")).json()["body_md"] == skill[
        "body_md"
    ]

    # Copies are per organization too.
    lib = await _published_library_skill(client, org.superuser)
    a_copy = (
        await a_dev.post(f"{SKILLS}/from-library/{lib['library_skill_uuid']}")
    ).json()
    b_copy = await b.post(f"{SKILLS}/from-library/{lib['library_skill_uuid']}")
    assert b_copy.status_code == 201
    assert b_copy.json()["skill_uuid"] != a_copy["skill_uuid"]
    assert (await b.get(f"{SKILLS}/{a_copy['skill_uuid']}")).status_code == 404


async def test_allowed_tool_uuids_are_org_scoped(client, org, other_org):
    admin = org.members[OrgRole.ADMIN]
    http = client(admin)
    own = await _create_tool(org.id, admin.id)
    archived = await _create_tool(org.id, admin.id, status=ToolStatus.ARCHIVED)
    foreign = await _create_tool(other_org.id, other_org.members[OrgRole.ADMIN].id)

    ok = await http.post(
        SKILLS, json=_skill_body(_name(), allowed_tool_uuids=[own, own])
    )
    assert ok.status_code == 201
    assert ok.json()["allowed_tool_uuids"] == [own]

    for bad in ([foreign], [archived], [str(uuid.uuid4())], [own, foreign]):
        response = await http.post(
            SKILLS, json=_skill_body(_name(), allowed_tool_uuids=bad)
        )
        assert response.status_code == 422, bad
        assert "Unknown tools" in response.json()["detail"]

    skill_uuid = ok.json()["skill_uuid"]
    rejected = await http.patch(
        f"{SKILLS}/{skill_uuid}", json={"allowed_tool_uuids": [foreign]}
    )
    assert rejected.status_code == 422
    unchanged = await http.patch(f"{SKILLS}/{skill_uuid}", json={"body_md": "b"})
    assert unchanged.json()["allowed_tool_uuids"] == [own]
    cleared = await http.patch(
        f"{SKILLS}/{skill_uuid}", json={"allowed_tool_uuids": None}
    )
    assert cleared.json()["allowed_tool_uuids"] is None


async def test_import_and_export(client, org):
    admin = org.members[OrgRole.ADMIN]
    http = client(admin)
    tool = await _create_tool(org.id, admin.id)
    from api.db.skill_client import FrontmatterExtra, SkillContent, SkillFile

    name = _name("imported")
    content = SkillContent(
        name=name,
        description="Imported skill.",
        body_md="# Imported\n\nSee references/a.md.",
        files=(SkillFile("references/a.md", "A"),),
        extra=FrontmatterExtra(metadata={"author": "test"}),
    )
    archive = export_skill_zip(content, allowed_tools=(tool,))

    imported = await http.post(
        f"{SKILLS}/import", files={"file": (f"{name}.zip", archive, "application/zip")}
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert (body["name"], body["allowed_tool_uuids"]) == (name, [tool])
    assert body["frontmatter_extra"]["metadata"] == {"author": "test"}

    exported = await http.get(f"{SKILLS}/{body['skill_uuid']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert f'filename="{name}.zip"' in exported.headers["content-disposition"]
    assert exported.content == archive

    # Same name again: 409 with a suggestion.
    dup = await http.post(
        f"{SKILLS}/import", files={"file": (f"{name}.zip", archive, "application/zip")}
    )
    assert dup.status_code == 409 and dup.json()["suggested_name"] == f"{name}-2"

    # A single SKILL.md upload works.
    single = f"---\nname: {_name('single')}\ndescription: One file.\n---\n\nBody\n"
    one = await http.post(
        f"{SKILLS}/import",
        files={"file": ("SKILL.md", single.encode(), "text/markdown")},
    )
    assert one.status_code == 201

    # allowed-tools naming tools that are not this workspace's: rejected.
    claude_style = (
        f"---\nname: {_name()}\ndescription: d\nallowed-tools: Read Grep\n---\nb"
    )
    rejected = await http.post(
        f"{SKILLS}/import", files={"file": ("SKILL.md", claude_style.encode())}
    )
    assert rejected.status_code == 422
    assert "Read, Grep" in rejected.json()["detail"]

    # Traversal inside a zip: rejected with a clear error.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bad:
        bad.writestr("SKILL.md", single)
        bad.writestr("../escape.md", "x")
    traversal = await http.post(
        f"{SKILLS}/import", files={"file": ("x.zip", buffer.getvalue())}
    )
    assert traversal.status_code == 422
    assert traversal.json()["code"] == "skill_invalid"


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", SKILLS, set(OrgRole)),
        ("POST", SKILLS, {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        ("POST", f"{SKILLS}/import", {OrgRole.DEVELOPER, OrgRole.ADMIN}),
        ("GET", LIBRARY, set(OrgRole)),
    ],
)
async def test_role_matrix(client, org, method, path, allowed):
    for role, user in org.members.items():
        response = await client(user).request(method, path)
        assert (response.status_code == 403) is (role not in allowed), (
            role,
            response.status_code,
        )


async def test_viewer_reads_but_cannot_write(client, org):
    dev = client(org.members[OrgRole.DEVELOPER])
    skill = (await dev.post(SKILLS, json=_skill_body(_name()))).json()
    skill_uuid = skill["skill_uuid"]
    lib = await _published_library_skill(client, org.superuser)

    viewer = client(org.members[OrgRole.VIEWER])
    assert (await viewer.get(f"{SKILLS}/{skill_uuid}")).status_code == 200
    assert (await viewer.get(f"{SKILLS}/{skill_uuid}/export")).status_code == 200
    assert (await viewer.post(SKILLS, json=_skill_body(_name()))).status_code == 403
    assert (
        await viewer.patch(f"{SKILLS}/{skill_uuid}", json={"body_md": "x"})
    ).status_code == 403
    assert (await viewer.delete(f"{SKILLS}/{skill_uuid}")).status_code == 403
    assert (
        await viewer.post(f"{SKILLS}/from-library/{lib['library_skill_uuid']}")
    ).status_code == 403
    assert (
        await viewer.post(f"{SKILLS}/{skill_uuid}/apply-library-update", json={})
    ).status_code == 403


# -- migration -----------------------------------------------------------------------------


async def test_migration_downgrade_and_upgrade(setup_test_database, monkeypatch):
    spec = importlib.util.spec_from_file_location("skills_migration", _MIGRATION_PATH)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    tables = {"skill_library", "skill_library_files", "skills", "skill_files"}

    engine = create_async_engine(setup_test_database)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()

            def run(sync_connection):
                monkeypatch.setattr(
                    migration,
                    "op",
                    Operations(MigrationContext.configure(sync_connection)),
                )
                migration.downgrade()
                assert not tables & set(sa.inspect(sync_connection).get_table_names())
                migration.upgrade()
                inspector = sa.inspect(sync_connection)
                assert tables <= set(inspector.get_table_names())
                indexes = {i["name"]: i for i in inspector.get_indexes("skills")}
                assert indexes["uq_skills_org_name_active"]["unique"]

            await connection.run_sync(run)
            await transaction.rollback()
    finally:
        await engine.dispose()
