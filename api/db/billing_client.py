"""Data access for billing accounts and the credit ledger."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import BillingAccountModel, BillingLedgerEntryModel
from api.enums import BillingLedgerEntryType, BillingPlan

_Entry = BillingLedgerEntryModel

# Matches the Numeric(14, 4) ledger columns.
_LEDGER_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class BillingAccount:
    id: int
    organization_id: int
    plan: BillingPlan
    balance_eur: Decimal
    credit_limit_eur: Decimal
    price_per_minute_eur: Decimal | None
    stripe_customer_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BillingLedgerEntry:
    id: int
    organization_id: int
    entry_type: BillingLedgerEntryType
    amount_eur: Decimal
    balance_after_eur: Decimal
    description: str | None
    workflow_run_id: int | None
    stripe_checkout_session_id: str | None
    created_by: int | None
    metadata: dict[str, Any]
    created_at: datetime


def _to_account(row: BillingAccountModel) -> BillingAccount:
    return BillingAccount(
        id=row.id,
        organization_id=row.organization_id,
        plan=BillingPlan(row.plan),
        balance_eur=row.balance_eur,
        credit_limit_eur=row.credit_limit_eur,
        price_per_minute_eur=row.price_per_minute_eur,
        stripe_customer_id=row.stripe_customer_id,
        created_at=row.created_at,
    )


def _to_entry(row: BillingLedgerEntryModel) -> BillingLedgerEntry:
    return BillingLedgerEntry(
        id=row.id,
        organization_id=row.organization_id,
        entry_type=BillingLedgerEntryType(row.entry_type),
        amount_eur=row.amount_eur,
        balance_after_eur=row.balance_after_eur,
        description=row.description,
        workflow_run_id=row.workflow_run_id,
        stripe_checkout_session_id=row.stripe_checkout_session_id,
        created_by=row.created_by,
        metadata=row.entry_metadata or {},
        created_at=row.created_at,
    )


async def _insert_account_if_missing(session: AsyncSession, organization_id: int):
    result = await session.execute(
        insert(BillingAccountModel)
        .values(organization_id=organization_id)
        .on_conflict_do_nothing(index_elements=["organization_id"])
        .returning(BillingAccountModel.id)
    )
    return result.scalar_one_or_none() is not None


async def _is_duplicate_entry(
    session: AsyncSession,
    *,
    entry_type: BillingLedgerEntryType,
    workflow_run_id: int | None,
    stripe_checkout_session_id: str | None,
) -> bool:
    if entry_type == BillingLedgerEntryType.USAGE and workflow_run_id is not None:
        existing = await session.execute(
            select(_Entry.id).where(
                _Entry.workflow_run_id == workflow_run_id,
                _Entry.entry_type == BillingLedgerEntryType.USAGE.value,
            )
        )
        if existing.first() is not None:
            return True
    if stripe_checkout_session_id is not None:
        existing = await session.execute(
            select(_Entry.id).where(
                _Entry.stripe_checkout_session_id == stripe_checkout_session_id
            )
        )
        if existing.first() is not None:
            return True
    return False


class BillingClient(BaseDBClient):
    async def ensure_billing_account(
        self, organization_id: int
    ) -> tuple[BillingAccount, bool]:
        """Return the organization's billing account, creating it if needed.

        The second value is True only for the call that created the account,
        so one-off setup (trial credit, Stripe customer) runs exactly once.
        """
        async with self.async_session() as session:
            created = await _insert_account_if_missing(session, organization_id)
            await session.commit()
            row = (
                await session.execute(
                    select(BillingAccountModel).where(
                        BillingAccountModel.organization_id == organization_id
                    )
                )
            ).scalar_one()
            return _to_account(row), created

    async def get_billing_account(self, organization_id: int) -> BillingAccount | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(BillingAccountModel).where(
                        BillingAccountModel.organization_id == organization_id
                    )
                )
            ).scalar_one_or_none()
            return _to_account(row) if row else None

    async def add_billing_ledger_entry(
        self,
        *,
        organization_id: int,
        entry_type: BillingLedgerEntryType,
        amount_eur: Decimal,
        description: str | None = None,
        workflow_run_id: int | None = None,
        stripe_checkout_session_id: str | None = None,
        created_by: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BillingLedgerEntry | None:
        """Append a ledger entry and move the cached balance with it.

        Idempotent: returns None, changing nothing, when this run was already
        charged or this Checkout session was already credited.
        """
        amount = Decimal(amount_eur).quantize(_LEDGER_QUANTUM, rounding=ROUND_HALF_UP)
        async with self.async_session() as session:
            await _insert_account_if_missing(session, organization_id)
            # The row lock serializes every balance change for the
            # organization, which also makes the duplicate check below safe.
            account = (
                await session.execute(
                    select(BillingAccountModel)
                    .where(BillingAccountModel.organization_id == organization_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()

            if await _is_duplicate_entry(
                session,
                entry_type=entry_type,
                workflow_run_id=workflow_run_id,
                stripe_checkout_session_id=stripe_checkout_session_id,
            ):
                # Nothing was changed; leaving the block releases the lock.
                return None

            account.balance_eur = account.balance_eur + amount
            row = BillingLedgerEntryModel(
                organization_id=organization_id,
                entry_type=entry_type.value,
                amount_eur=amount,
                balance_after_eur=account.balance_eur,
                description=description,
                workflow_run_id=workflow_run_id,
                stripe_checkout_session_id=stripe_checkout_session_id,
                created_by=created_by,
                entry_metadata=metadata or {},
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # The unique indexes are the backstop for the check above.
                await session.rollback()
                return None
            await session.refresh(row)
            return _to_entry(row)

    async def list_billing_ledger_entries(
        self,
        organization_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        entry_type: BillingLedgerEntryType | None = None,
    ) -> tuple[list[BillingLedgerEntry], int]:
        """Newest-first page of the organization's ledger, and the total count."""
        conditions = [_Entry.organization_id == organization_id]
        if entry_type is not None:
            conditions.append(_Entry.entry_type == entry_type.value)
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(_Entry).where(*conditions)
                )
            ).scalar_one()
            rows = (
                (
                    await session.execute(
                        select(_Entry)
                        .where(*conditions)
                        .order_by(_Entry.created_at.desc(), _Entry.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                )
                .scalars()
                .all()
            )
            return [_to_entry(row) for row in rows], total
