"""Home layout: which cards show, resolved person > workspace > platform >
built-in, and who may save each level."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.app import app
from api.db import db_client
from api.db.models import OrganizationModel, UserModel
from api.enums import OrgRole
from api.services.auth.depends import get_user
from api.services.dashboard import home_layout
from api.services.dashboard.home_layout import (
    BUILT_IN_LAYOUT,
    HomeLayout,
    parse_layout,
    resolve_layout,
)

# -- the rules ----------------------------------------------------------------


def test_card_ids_are_deduplicated_in_order():
    layout = HomeLayout(hidden=["tiles", "tiles", "quick-links"], pinned=["attention"])
    assert layout.hidden == ["tiles", "quick-links"]
    assert layout.pinned == ["attention"]


@pytest.mark.parametrize("bad", ["", "Tiles", "a b", "x" * 41, "<script>"])
def test_card_ids_must_look_like_card_ids(bad):
    with pytest.raises(ValidationError):
        HomeLayout(hidden=[bad])


def test_too_many_cards_are_refused():
    with pytest.raises(ValidationError):
        HomeLayout(pinned=[f"card-{i}" for i in range(31)])


def test_unknown_card_ids_are_kept():
    # A layout saved by a newer app still reads in an older one.
    assert HomeLayout(hidden=["card-from-the-future"]).hidden == [
        "card-from-the-future"
    ]


def test_resolution_order():
    person = HomeLayout(pinned=["recent-calls"])
    workspace = HomeLayout(hidden=["tiles"])
    platform = HomeLayout(hidden=["quick-links"])
    assert resolve_layout(person, workspace, platform) == (person, "person")
    assert resolve_layout(None, workspace, platform) == (workspace, "workspace")
    assert resolve_layout(None, None, platform) == (platform, "platform")
    assert resolve_layout(None, None, None) == (BUILT_IN_LAYOUT, "default")


def test_an_empty_saved_layout_still_counts():
    # "Show everything" saved by a person is a choice, not "nothing saved".
    assert parse_layout({"hidden": [], "pinned": []}, "test") == HomeLayout()
    assert resolve_layout(HomeLayout(), HomeLayout(hidden=["tiles"]), None)[1] == (
        "person"
    )


def test_unreadable_stored_layout_is_ignored():
    assert parse_layout({"hidden": "tiles"}, "test") is None
    assert parse_layout(None, "test") is None
    assert parse_layout({}, "test") is None


def test_built_in_layout_shows_every_card():
    assert BUILT_IN_LAYOUT.hidden == []
    assert BUILT_IN_LAYOUT.pinned == []


# -- through the API, with real memberships -----------------------------------


@pytest.fixture(scope="module")
async def sessions(setup_test_database):
    engine = create_async_engine(setup_test_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_session = db_client.engine, db_client.async_session
    db_client.engine, db_client.async_session = engine, factory
    yield factory
    db_client.engine, db_client.async_session = old_engine, old_session
    await engine.dispose()


@pytest.fixture
async def org(sessions):
    async with sessions() as session:
        organization = OrganizationModel(provider_id=f"layout-{uuid.uuid4().hex}")
        session.add(organization)
        await session.commit()
    members = {}
    for role in OrgRole:
        async with sessions() as session:
            user = UserModel(
                provider_id=f"layout-{uuid.uuid4().hex}",
                email=f"{role}-{uuid.uuid4().hex}@example.com",
                selected_organization_id=organization.id,
            )
            session.add(user)
            await session.commit()
        await db_client.add_user_to_organization(user.id, organization.id, role=role)
        members[role] = user
    return SimpleNamespace(id=organization.id, members=members)


@pytest.fixture
async def client_as(org):
    current = SimpleNamespace(user=None)

    async def _user():
        async with db_client.async_session() as session:
            return await session.scalar(
                select(UserModel).where(UserModel.id == current.user.id)
            )

    app.dependency_overrides[get_user] = _user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:

        def as_role(role: OrgRole) -> AsyncClient:
            current.user = org.members[role]
            return client

        yield as_role
    app.dependency_overrides.pop(get_user, None)


@pytest.fixture
async def no_platform_layout(org):
    # The platform default is shared by every test: start and end without one.
    admin = org.members[OrgRole.ADMIN].id
    await home_layout.save_platform_layout(None, actor_user_id=admin, action="test")
    yield
    await home_layout.save_platform_layout(None, actor_user_id=admin, action="test")


LAYOUT = "/api/v1/dashboard/layout"


@pytest.mark.real_org_roles
async def test_levels_resolve_in_order(client_as, org, no_platform_layout):
    staff, admin = OrgRole.STAFF, OrgRole.ADMIN

    body = (await client_as(staff).get(LAYOUT)).json()
    assert body["source"] == "default"
    assert body["layout"] == BUILT_IN_LAYOUT.model_dump()
    assert body["can_set_workspace_default"] is False
    assert {c["id"] for c in body["cards"]} >= {"attention", "recent-calls"}

    # The platform default applies to a workspace without its own.
    await home_layout.save_platform_layout(
        HomeLayout(hidden=["quick-links"]),
        actor_user_id=org.members[admin].id,
        action="test",
    )
    body = (await client_as(staff).get(LAYOUT)).json()
    assert body["source"] == "platform"
    assert body["layout"]["hidden"] == ["quick-links"]

    # An admin's workspace default beats the platform's.
    response = await client_as(admin).put(
        f"{LAYOUT}/workspace", json={"hidden": ["tiles"], "pinned": ["attention"]}
    )
    assert response.status_code == 200
    assert response.json()["can_set_workspace_default"] is True
    body = (await client_as(staff).get(LAYOUT)).json()
    assert body["source"] == "workspace"
    assert body["layout"] == {"hidden": ["tiles"], "pinned": ["attention"]}

    # A person's own layout beats the workspace's, for them only.
    response = await client_as(staff).put(LAYOUT, json={"pinned": ["recent-calls"]})
    assert response.status_code == 200
    assert response.json()["source"] == "person"
    assert response.json()["layout"] == {"hidden": [], "pinned": ["recent-calls"]}
    assert response.json()["workspace_default"]["hidden"] == ["tiles"]
    assert (await client_as(OrgRole.VIEWER).get(LAYOUT)).json()["source"] == (
        "workspace"
    )

    # Reset: back to the workspace default.
    body = (await client_as(staff).delete(LAYOUT)).json()
    assert body["source"] == "workspace"

    # Clearing the workspace default: the platform's applies again.
    body = (await client_as(admin).delete(f"{LAYOUT}/workspace")).json()
    assert body["source"] == "platform"
    assert body["workspace_default"] is None


@pytest.mark.real_org_roles
async def test_bad_card_ids_are_refused(client_as):
    response = await client_as(OrgRole.STAFF).put(LAYOUT, json={"hidden": ["<b>"]})
    assert response.status_code == 422


@pytest.mark.real_org_roles
async def test_platform_default_is_for_platform_admins_only(
    sessions, client_as, org, no_platform_layout
):
    path = "/api/v1/superuser/admin/home-layout"
    for role in OrgRole:
        assert (await client_as(role).get(path)).status_code == 403
        assert (
            await client_as(role).put(path, json={"layout": {"hidden": []}})
        ).status_code == 403

    admin = org.members[OrgRole.ADMIN]
    async with sessions() as session:
        user = await session.get(UserModel, admin.id)
        user.is_superuser = True
        await session.commit()

    body = (await client_as(OrgRole.ADMIN).get(path)).json()
    assert body["layout"] is None
    assert body["built_in"] == BUILT_IN_LAYOUT.model_dump()

    response = await client_as(OrgRole.ADMIN).put(
        path, json={"layout": {"hidden": ["tiles"], "pinned": []}}
    )
    assert response.status_code == 200
    assert response.json()["layout"] == {"hidden": ["tiles"], "pinned": []}
    entries, _ = await db_client.list_platform_audit_entries(
        limit=5, action_prefix="home_layout."
    )
    assert entries and entries[0].actor_user_id == admin.id

    response = await client_as(OrgRole.ADMIN).put(path, json={"layout": None})
    assert response.json()["layout"] is None
