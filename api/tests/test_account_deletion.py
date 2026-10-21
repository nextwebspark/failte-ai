"""Deleting your own account, and the account and organisation exports."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from api import constants
from api.db.models import (
    APIKeyModel,
    CampaignModel,
    EmbedTokenModel,
    ExternalCredentialModel,
    KnowledgeBaseDocumentModel,
    ToolModel,
    UserConfigurationModel,
    UserModel,
    WorkflowModel,
    WorkflowRecordingModel,
    organization_users_association,
)
from api.enums import OrgRole
from api.services.auth import depends as auth_depends
from api.services.auth.stack_auth import StackAuthDeletionError
from api.services.privacy import account_deletion
from api.services.privacy.data_export import redact_secrets
from api.tests.support.privacy_seed import (
    SECRET,
    FakeStorage,
    add_member,
    make_user,
    seed_organization,
)

pytestmark = pytest.mark.real_org_roles


@pytest.fixture
def storage():
    return FakeStorage()


async def seeded(async_session, storage, **kwargs):
    data = await seed_organization(async_session, storage, **kwargs)
    await async_session.commit()
    return data


async def delete_me(client, email):
    return await client.request(
        "DELETE", "/api/v1/user/me", json={"confirm_email": email}
    )


async def user_exists(session, user_id) -> bool:
    count = await session.execute(
        select(func.count()).select_from(UserModel).where(UserModel.id == user_id)
    )
    return count.scalar_one() == 1


# --- deleting an account ------------------------------------------------------


async def test_last_admin_of_an_organization_with_members_is_refused(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.admin) as client:
        response = await delete_me(client, data.admin.email)
    assert response.status_code == 409
    assert response.json()["code"] == "last_admin_of_organization"
    assert response.json()["organization_id"] == str(data.org.id)
    assert await user_exists(async_session, data.admin.id)


async def test_sole_member_is_told_to_delete_the_organization_first(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    loner = await make_user(async_session)
    from api.db.models import OrganizationModel

    own = OrganizationModel(provider_id=f"org_solo_{loner.id}", name="Solo")
    async_session.add(own)
    await async_session.flush()
    await add_member(async_session, loner, own, OrgRole.ADMIN)
    await add_member(async_session, loner, data.org, OrgRole.VIEWER)
    await async_session.commit()

    async with test_client_factory(loner) as client:
        response = await delete_me(client, loner.email)
    assert response.status_code == 409
    assert response.json()["code"] == "sole_member_of_organization"
    assert response.json()["organization_id"] == str(own.id)

    # Once that organisation is scheduled for deletion it no longer blocks.
    await db_session.request_organization_deletion(
        own.id,
        requested_at=own.created_at or data.org.created_at,
        scheduled_for=data.org.created_at,
    )
    async with test_client_factory(loner) as client:
        response = await delete_me(client, loner.email)
    assert response.status_code == 204
    assert not await user_exists(async_session, loner.id)


async def test_confirmation_must_match_the_email(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.developer) as client:
        response = await delete_me(client, "someone@else.test")
    assert response.status_code == 400
    assert response.json()["code"] == "confirmation_mismatch"
    assert await user_exists(async_session, data.developer.id)


async def test_deleting_an_account_keeps_what_they_created(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    developer_id = data.developer.id
    async_session.add(
        UserConfigurationModel(
            user_id=developer_id, key="MODEL_CONFIGURATION", configuration={"a": 1}
        )
    )
    await async_session.commit()

    async with test_client_factory(data.developer) as client:
        response = await delete_me(client, data.developer.email.upper())
    assert response.status_code == 204

    assert not await user_exists(async_session, developer_id)
    memberships = await async_session.execute(
        select(func.count())
        .select_from(organization_users_association)
        .where(organization_users_association.c.user_id == developer_id)
    )
    assert memberships.scalar_one() == 0
    configs = await async_session.execute(
        select(func.count())
        .select_from(UserConfigurationModel)
        .where(UserConfigurationModel.user_id == developer_id)
    )
    assert configs.scalar_one() == 0

    # Everything they created stays with the organisation, creator cleared.
    for model, column in (
        (WorkflowModel, WorkflowModel.user_id),
        (CampaignModel, CampaignModel.created_by),
        (ToolModel, ToolModel.created_by),
        (ExternalCredentialModel, ExternalCredentialModel.created_by),
        (KnowledgeBaseDocumentModel, KnowledgeBaseDocumentModel.created_by),
        (WorkflowRecordingModel, WorkflowRecordingModel.created_by),
        (EmbedTokenModel, EmbedTokenModel.created_by),
        (APIKeyModel, APIKeyModel.created_by),
    ):
        rows = (
            await async_session.execute(
                select(column).where(model.organization_id == data.org.id)
            )
        ).all()
        assert rows, model
        assert {row[0] for row in rows} == {None}, model

    # Widget tokens survive; the user's API keys are archived.
    await async_session.refresh(data.embed_token)
    assert data.embed_token.is_active is True
    await async_session.refresh(data.api_key)
    assert data.api_key.is_active is False
    assert data.api_key.archived_at is not None


async def test_a_deleted_users_session_no_longer_works(
    db_session, async_session, storage, monkeypatch
):
    data = await seeded(async_session, storage)
    from api.utils.auth import create_jwt_token

    token = create_jwt_token(data.developer.id, data.developer.email)
    await account_deletion.delete_user_account(
        data.developer, confirm_email=data.developer.email
    )
    with pytest.raises(HTTPException) as exc:
        await auth_depends._handle_oss_auth(f"Bearer {token}")
    assert exc.value.status_code == 401


async def test_stack_user_is_deleted_first_and_a_failure_deletes_nothing(
    db_session, async_session, storage, monkeypatch
):
    data = await seeded(async_session, storage)
    # The failed attempt rolls back, which expires the loaded rows.
    developer = SimpleNamespace(
        id=data.developer.id,
        email=data.developer.email,
        provider_id=data.developer.provider_id,
    )
    monkeypatch.setattr(constants, "AUTH_PROVIDER", "stack")
    failing = AsyncMock(side_effect=StackAuthDeletionError("boom"))
    monkeypatch.setattr(account_deletion.stackauth, "delete_user", failing)

    with pytest.raises(Exception) as exc:
        await account_deletion.delete_user_account(
            developer, confirm_email=developer.email
        )
    assert getattr(exc.value, "code", None) == "identity_provider_error"
    assert await user_exists(async_session, developer.id)

    deleted = AsyncMock()
    monkeypatch.setattr(account_deletion.stackauth, "delete_user", deleted)
    await account_deletion.delete_user_account(developer, confirm_email=developer.email)
    deleted.assert_awaited_once_with(developer.provider_id)
    assert not await user_exists(async_session, developer.id)


# --- exports --------------------------------------------------------------------


async def test_account_export_has_no_credentials(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.admin) as client:
        response = await client.get("/api/v1/user/me/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert body["profile"]["email"] == data.admin.email
    assert body["profile"]["has_password"] is True
    assert body["memberships"] == [
        {
            "organization_id": data.org.id,
            "organization_name": "Acme Ltd",
            "role": "admin",
        }
    ]
    assert "onboarding" in body
    raw = response.text
    assert "password_hash" not in raw
    assert "argon2" not in raw
    assert data.admin.google_sub not in raw


async def test_organization_export_has_no_secrets_or_call_content(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.admin) as client:
        response = await client.get("/api/v1/organizations/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    raw = json.dumps(body)

    assert SECRET not in raw
    assert data.api_key.key_hash not in raw
    assert data.embed_token.token not in raw
    assert "+353870000001" not in raw  # caller number from call content
    assert "password_hash" not in raw

    assert body["organization"]["name"] == "Acme Ltd"
    assert {m["role"] for m in body["members"]} == {"admin", "developer"}
    [agent] = body["agents"]
    assert agent["name"] == "Receptionist"
    assert agent["definitions"]
    assert [t["name"] for t in body["tools"]] == ["CRM lookup"]
    assert [c["name"] for c in body["campaigns"]] == ["Renewals", "Old"]
    assert [d["filename"] for d in body["knowledge_base_documents"]] == ["faq.pdf"]
    assert [p["address"] for p in body["phone_numbers"]] == ["+35315550100"]
    assert [c["name"] for c in body["telephony_configurations"]] == ["Twilio"]
    assert [e["amount_eur"] for e in body["billing_ledger"]] == [-1.2]
    assert body["billing_account"] is not None


def test_redaction_covers_nested_secret_keys():
    redacted = redact_secrets(
        {
            "headers": {"Authorization": "Bearer x", "Accept": "json"},
            "auth": [{"api_key": "k", "password": "p", "user": "u"}],
            "client_secret": "",
        }
    )
    assert redacted == {
        "headers": {"Authorization": "[redacted]", "Accept": "json"},
        "auth": [{"api_key": "[redacted]", "password": "[redacted]", "user": "u"}],
        "client_secret": "",
    }


async def test_stack_user_is_not_deleted_when_the_locked_check_refuses(
    db_session, async_session, storage, monkeypatch
):
    """The unlocked pre-check passed, but by the time the locks are held the
    user is the last admin: Stack must never be asked to delete them."""
    data = await seeded(async_session, storage)
    monkeypatch.setattr(constants, "AUTH_PROVIDER", "stack")
    delete_stack_user = AsyncMock()
    monkeypatch.setattr(account_deletion.stackauth, "delete_user", delete_stack_user)
    # Simulate the race: the pre-check saw a second admin who has gone since.
    monkeypatch.setattr(
        account_deletion.db_client, "check_user_account_deletable", AsyncMock()
    )

    with pytest.raises(Exception) as exc:
        await account_deletion.delete_user_account(
            data.admin, confirm_email=data.admin.email
        )

    assert getattr(exc.value, "code", None) == "last_admin_of_organization"
    delete_stack_user.assert_not_awaited()
    assert await user_exists(async_session, data.admin.id)


async def test_last_admin_of_a_pending_organization_with_members_is_refused(
    db_session, async_session, storage, test_client_factory
):
    """Someone must stay able to export or cancel until erasure."""
    data = await seeded(async_session, storage)
    await db_session.request_organization_deletion(
        data.org.id,
        requested_at=data.org.created_at,
        scheduled_for=data.org.created_at,
    )
    async with test_client_factory(data.admin) as client:
        response = await delete_me(client, data.admin.email)
    assert response.status_code == 409
    assert response.json()["code"] == "last_admin_of_organization"
    assert await user_exists(async_session, data.admin.id)
