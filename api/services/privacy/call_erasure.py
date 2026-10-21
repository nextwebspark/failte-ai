"""Answering callers' data requests: export and erase their calls.

An organization using LightMove is the controller of its callers' data and we
are its processor (GDPR Art. 28(3)(e)), so it must be able to act on a
caller's request for access (Art. 15) or erasure (Art. 17):

* ``erase_workflow_run`` erases one call.
* ``export_subject_data`` gathers everything stored about one phone number.
* ``erase_subject_data`` erases it.

Erasure scrubs, it does not delete. A run keeps its date, duration, status,
disposition and cost, because the billing ledger points at it and must be
kept for six years; recordings, transcripts, call context, logs and the phone
numbers go. Stored objects are deleted first and a run is only scrubbed once
all of its objects are gone (the retention purge's rule), so a storage outage
never leaves a scrubbed row with a recording nobody can find any more.

A number matches a run when any of ``caller_number``, ``called_number`` or
``phone_number`` in its call context normalizes to it: the caller of an
inbound call, the callee of an outbound one. Stored values are not
normalized, so SQL only narrows the rows down and Python compares. The
organization's own numbers sit on the other side of every call, so a request
for one of them is refused rather than matching every call.
"""

import csv
import io
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Optional

from loguru import logger

from api.db import db_client
from api.db.privacy_client import (
    QUEUED_RUN_IN_FLIGHT_STATE,
    ErasableWorkflowRun,
    NumberPrefilter,
    SubjectQueuedRun,
    SubjectWorkflowRun,
)
from api.db.retention_client import CALL_CONTEXT_NUMBER_KEYS
from api.schemas.privacy import (
    SUBJECT_NUMBER_MAX_LENGTH,
    SubjectCallData,
    SubjectDataResponse,
    SubjectErasureResponse,
    SubjectQueuedCall,
    SubjectRecordingUrls,
    SubjectTranscriptLine,
)
from api.services.filesystem import BaseFileSystem
from api.services.retention.purge import (
    StorageResolver,
    campaign_csv_key,
    current_storage_backend,
    default_storage_resolver,
    delete_run_objects,
)
from api.utils.recording_artifacts import (
    RecordingTrack,
    get_recording_storage_backend,
    get_recording_storage_key,
)
from api.utils.telephony_address import normalize_telephony_address

# An unfinished run with activity this recent may be a call still going on.
# A voice call never lasts this long, so an older unfinished run is abandoned.
RUN_ACTIVE_WINDOW = timedelta(hours=6)
# Signed links in an export: the most any link to call content may live.
SIGNED_URL_EXPIRES_IN = 3600
# Calls one export returns. Erasure has no limit.
EXPORT_CALL_LIMIT = 1000
CANDIDATE_PAGE_SIZE = 500
RUN_BATCH_SIZE = 100
# Digits of a PSTN number the SQL prefilter matches on: enough to be selective,
# few enough to ignore how the country code was written.
PREFILTER_DIGITS = 7


class CallErasureError(Exception):
    """Base for the reasons a call cannot be erased."""


class WorkflowRunNotFoundError(CallErasureError):
    pass


class WorkflowRunInProgressError(CallErasureError):
    pass


class StoredObjectsNotDeletedError(CallErasureError):
    """Some stored object of the run could not be deleted; nothing was scrubbed."""


class InvalidSubjectNumberError(ValueError):
    pass


class OrganizationNumberError(ValueError):
    """The number is one of the organization's own numbers."""


# --- numbers -----------------------------------------------------------------


@dataclass(frozen=True)
class SubjectNumber:
    canonical: str
    prefilter: NumberPrefilter


def _canonical(value: str) -> Optional[str]:
    try:
        return normalize_telephony_address(value).canonical
    except ValueError:
        return None


def address_forms(value: Any) -> set[str]:
    """Every canonical address a stored value can stand for.

    A SIP URI also stands for its user part, so ``sip:+35312345678@pbx``
    matches the number ``+353 1 234 5678``.
    """
    if not isinstance(value, str) or not value.strip():
        return set()
    forms = set()
    normalized = None
    try:
        normalized = normalize_telephony_address(value)
        forms.add(normalized.canonical)
    except ValueError:
        return forms
    if normalized.address_type == "sip_uri":
        user = value.strip().split(":", 1)[1].split("@", 1)
        if len(user) == 2:
            user_part = user[0].split(";", 1)[0]
            user_form = _canonical(user_part)
            if user_form:
                forms.add(user_form)
    return forms


def parse_subject_number(raw: str) -> SubjectNumber:
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidSubjectNumberError("Enter a phone number.")
    if len(raw) > SUBJECT_NUMBER_MAX_LENGTH:
        raise InvalidSubjectNumberError("That number is too long.")
    normalized = normalize_telephony_address(raw)
    canonical = normalized.canonical
    if normalized.address_type == "pstn":
        digits = canonical.lstrip("+")
        prefilter = NumberPrefilter(digits=digits[-PREFILTER_DIGITS:])
    elif normalized.address_type == "sip_uri":
        rest = canonical.split(":", 1)[1]
        user, _, host = rest.partition("@")
        prefilter = NumberPrefilter(fragment=user if host else rest)
    else:
        prefilter = NumberPrefilter(fragment=canonical)
    if len((prefilter.digits or prefilter.fragment or "").strip()) < 3:
        raise InvalidSubjectNumberError("That number is too short to search for.")
    return SubjectNumber(canonical=canonical, prefilter=prefilter)


def context_names_subject(context: Any, subject: SubjectNumber) -> bool:
    if not isinstance(context, dict):
        return False
    return any(
        subject.canonical in address_forms(context.get(key))
        for key in CALL_CONTEXT_NUMBER_KEYS
    )


async def resolve_subject_number(organization_id: int, raw: str) -> SubjectNumber:
    """The number a request is about, refusing the organization's own numbers."""
    subject = parse_subject_number(raw)
    for address, address_normalized in await db_client.get_organization_phone_addresses(
        organization_id
    ):
        if subject.canonical in address_forms(address) | address_forms(
            address_normalized
        ):
            raise OrganizationNumberError(
                "That is one of your organization's own numbers. Enter the "
                "caller's number."
            )
    return subject


async def find_subject_run_ids(
    organization_id: int, subject: SubjectNumber
) -> list[int]:
    run_ids = []
    after_id = 0
    while True:
        candidates = await db_client.find_workflow_run_number_candidates(
            organization_id=organization_id,
            prefilter=subject.prefilter,
            after_id=after_id,
            limit=CANDIDATE_PAGE_SIZE,
        )
        run_ids.extend(
            run_id
            for run_id, context in candidates
            if context_names_subject(context, subject)
        )
        if len(candidates) < CANDIDATE_PAGE_SIZE:
            return run_ids
        after_id = candidates[-1][0]


async def find_subject_queued_runs(
    organization_id: int, subject: SubjectNumber
) -> list[SubjectQueuedRun]:
    rows = []
    after_id = 0
    while True:
        candidates = await db_client.find_queued_run_number_candidates(
            organization_id=organization_id,
            prefilter=subject.prefilter,
            after_id=after_id,
            limit=CANDIDATE_PAGE_SIZE,
        )
        rows.extend(
            row
            for row in candidates
            if subject.canonical
            in address_forms(row.context_variables.get("phone_number"))
        )
        if len(candidates) < CANDIDATE_PAGE_SIZE:
            return rows
        after_id = candidates[-1].id


# --- one call ----------------------------------------------------------------


def is_run_in_progress(run: ErasableWorkflowRun, now: datetime) -> bool:
    """Whether the run may still be a live call or an open chat."""
    if run.is_completed:
        return False
    activity = [moment for moment in (run.created_at, run.chat_updated_at) if moment]
    return bool(activity) and max(activity) >= now - RUN_ACTIVE_WINDOW


async def _erase_runs(
    organization_id: int,
    runs: Iterable[ErasableWorkflowRun],
    now: datetime,
    resolve_storage: StorageResolver,
) -> tuple[list[int], list[int], list[int], int]:
    """Erase finished runs. Returns ``(erased, in progress, failed, objects)``."""
    erased, in_progress, failed = [], [], []
    objects = 0
    for run in runs:
        if is_run_in_progress(run, now):
            in_progress.append(run.id)
            continue
        deleted = await delete_run_objects(run.objects, resolve_storage)
        if deleted is None:
            failed.append(run.id)
            continue
        objects += deleted
        erased.append(run.id)
    if erased:
        # Runs purged already are skipped by the scrub, but their side data
        # is cleared again, so a retry after a partial failure completes.
        await db_client.scrub_workflow_runs_call_content(
            organization_id=organization_id, run_ids=erased, purged_at=now
        )
        await db_client.scrub_workflow_run_side_data(
            organization_id=organization_id, run_ids=erased
        )
    return erased, in_progress, failed, objects


async def erase_workflow_run(
    *,
    organization_id: int,
    workflow_id: int,
    run_id: int,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
) -> int:
    """Erase one call's content. Returns the number of stored objects deleted.

    Raises ``WorkflowRunNotFoundError`` when the organization has no such run
    under ``workflow_id``, ``WorkflowRunInProgressError`` while it may still be
    running, and ``StoredObjectsNotDeletedError`` (with nothing scrubbed) when
    storage fails.
    """
    now = now or datetime.now(UTC)
    runs = await db_client.get_erasable_workflow_runs(
        organization_id=organization_id, run_ids=[run_id], workflow_id=workflow_id
    )
    if not runs:
        raise WorkflowRunNotFoundError()
    _, in_progress, failed, objects = await _erase_runs(
        organization_id, runs, now, resolve_storage or default_storage_resolver()
    )
    if in_progress:
        raise WorkflowRunInProgressError()
    if failed:
        raise StoredObjectsNotDeletedError()
    logger.info(
        f"Erased call content of workflow run {run_id} "
        f"(organization {organization_id}, {objects} objects)"
    )
    return objects


# --- export ------------------------------------------------------------------


async def _signed_url(
    resolve_storage: StorageResolver, backend: str, key: Optional[str]
) -> Optional[str]:
    if not key:
        return None
    try:
        return await resolve_storage(backend).aget_signed_url(
            key, expiration=SIGNED_URL_EXPIRES_IN
        )
    except Exception as exc:
        logger.warning(f"Could not sign a call data link: {type(exc).__name__}")
        return None


async def _run_files(
    run: SubjectWorkflowRun, resolve_storage: StorageResolver
) -> SubjectRecordingUrls:
    async def track(name: RecordingTrack, fallback: Optional[str] = None):
        key = get_recording_storage_key(run.extra, name) or fallback
        backend = get_recording_storage_backend(run.extra, name) or run.storage_backend
        return await _signed_url(resolve_storage, backend, key)

    return SubjectRecordingUrls(
        recording=await track("mixed", run.recording_url),
        user_recording=await track("user"),
        bot_recording=await track("bot"),
        transcript=await _signed_url(
            resolve_storage, run.storage_backend, run.transcript_url
        ),
    )


def _transcript(logs: dict[str, Any]) -> list[SubjectTranscriptLine]:
    from api.services.workflow.qa.conversation import build_conversation_structure

    events = logs.get("realtime_feedback_events")
    if not isinstance(events, list) or not events:
        return []
    try:
        return [
            SubjectTranscriptLine(**line)
            for line in build_conversation_structure(events)
        ]
    except Exception as exc:
        # A malformed event means no readable transcript, not a failed export.
        logger.warning(f"Could not build a transcript: {type(exc).__name__}")
        return []


def _duration_seconds(usage_info: dict[str, Any]) -> Optional[float]:
    value = usage_info.get("call_duration_seconds")
    return float(value) if isinstance(value, (int, float)) else None


async def export_subject_data(
    *,
    organization_id: int,
    number: str,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
) -> SubjectDataResponse:
    """Everything the organization stores about calls with ``number``."""
    now = now or datetime.now(UTC)
    resolve_storage = resolve_storage or default_storage_resolver()
    subject = await resolve_subject_number(organization_id, number)

    run_ids = await find_subject_run_ids(organization_id, subject)
    truncated = len(run_ids) > EXPORT_CALL_LIMIT
    runs = await db_client.get_subject_workflow_runs(
        organization_id=organization_id, run_ids=run_ids[:EXPORT_CALL_LIMIT]
    )
    calls = []
    for run in runs:
        gathered = run.gathered_context
        chat = run.chat_session_data or {}
        calls.append(
            SubjectCallData(
                id=run.id,
                workflow_id=run.workflow_id,
                workflow_name=run.workflow_name,
                name=run.name,
                created_at=run.created_at,
                direction=run.call_type,
                status=run.state,
                disposition=gathered.get("mapped_call_disposition")
                or gathered.get("call_disposition"),
                duration_seconds=_duration_seconds(run.usage_info),
                in_progress=not run.is_completed
                and run.created_at is not None
                and run.created_at >= now - RUN_ACTIVE_WINDOW,
                already_erased="purged_at" in run.extra,
                initial_context=run.initial_context,
                gathered_context=gathered,
                annotations=run.annotations,
                transcript=_transcript(run.logs),
                chat_turns=list(chat.get("turns") or [])
                if isinstance(chat.get("turns"), list)
                else [],
                files=await _run_files(run, resolve_storage),
            )
        )

    queued_calls = [
        SubjectQueuedCall(
            id=row.id,
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            state=row.state,
            created_at=row.created_at,
            scheduled_for=row.scheduled_for,
            context_variables=row.context_variables,
        )
        for row in await find_subject_queued_runs(organization_id, subject)
    ]
    logger.info(
        f"Exported data for a caller of organization {organization_id}: "
        f"{len(calls)} calls, {len(queued_calls)} campaign contacts"
    )
    return SubjectDataResponse(
        number=subject.canonical,
        generated_at=now,
        signed_urls_expire_in=SIGNED_URL_EXPIRES_IN,
        calls=calls,
        queued_calls=queued_calls,
        truncated=truncated,
    )


# --- erase ---------------------------------------------------------------------


@dataclass
class _CsvOutcome:
    rewritten: int = 0
    rows_removed: int = 0
    failed: list[int] = field(default_factory=list)


def remove_subject_rows(content: bytes, subject: SubjectNumber) -> tuple[bytes, int]:
    """The CSV without the subject's rows, and how many rows were removed.

    A removed row is emptied rather than dropped: rows are numbered by
    position when a campaign syncs (``csv_{hash}_row_{n}``), and redials find
    a contact by that id, so the other rows must keep their place. A row with
    no phone number is skipped by the sync.
    """
    has_bom = content.startswith(b"\xef\xbb\xbf")
    text = content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if len(rows) < 2:
        return content, 0
    headers = [header.strip().lower() for header in rows[0]]
    if "phone_number" not in headers:
        return content, 0
    phone_index = headers.index("phone_number")

    removed = 0
    for index, row in enumerate(rows[1:], start=1):
        if len(row) > phone_index and subject.canonical in address_forms(
            row[phone_index]
        ):
            rows[index] = [""] * len(row)
            removed += 1
    if not removed:
        return content, 0

    output = io.StringIO(newline="")
    line_terminator = "\r\n" if "\r\n" in text else "\n"
    csv.writer(output, lineterminator=line_terminator).writerows(rows)
    data = output.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data if has_bom else data), removed


async def _rewrite_csv(
    storage: BaseFileSystem, key: str, subject: SubjectNumber
) -> Optional[int]:
    """Rows removed from the stored CSV, or None if it could not be rewritten."""
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "contacts.csv")
            if not await storage.adownload_file(key, path):
                return None
            with open(path, "rb") as handle:
                content = handle.read()
        rewritten, removed = remove_subject_rows(content, subject)
        if removed and not await storage.acreate_file_from_bytes(key, rewritten):
            return None
        return removed
    except Exception as exc:
        logger.warning(
            f"Could not rewrite a campaign contact list: {type(exc).__name__}"
        )
        return None


async def _erase_from_campaign_lists(
    organization_id: int, subject: SubjectNumber, resolve_storage: StorageResolver
) -> _CsvOutcome:
    outcome = _CsvOutcome()
    done: dict[str, Optional[int]] = {}
    storage = resolve_storage(current_storage_backend())
    for campaign in await db_client.get_campaign_csv_sources(organization_id):
        key = campaign_csv_key(organization_id, campaign)
        if key is None:
            continue
        if key not in done:
            # Redial campaigns share their parent's list: rewrite it once.
            done[key] = await _rewrite_csv(storage, key, subject)
            if done[key]:
                outcome.rewritten += 1
                outcome.rows_removed += done[key]
        if done[key] is None:
            outcome.failed.append(campaign.id)
    return outcome


async def erase_subject_data(
    *,
    organization_id: int,
    number: str,
    now: Optional[datetime] = None,
    resolve_storage: Optional[StorageResolver] = None,
) -> SubjectErasureResponse:
    """Erase every call and campaign contact of ``number`` in the organization.

    Calls still in progress, and calls whose files could not be deleted, are
    left untouched and reported, so the request can simply be repeated.
    """
    now = now or datetime.now(UTC)
    resolve_storage = resolve_storage or default_storage_resolver()
    subject = await resolve_subject_number(organization_id, number)

    erased, in_progress, failed, objects = [], [], [], 0
    run_ids = await find_subject_run_ids(organization_id, subject)
    for start in range(0, len(run_ids), RUN_BATCH_SIZE):
        runs = await db_client.get_erasable_workflow_runs(
            organization_id=organization_id,
            run_ids=run_ids[start : start + RUN_BATCH_SIZE],
        )
        batch = await _erase_runs(organization_id, runs, now, resolve_storage)
        erased += batch[0]
        in_progress += batch[1]
        failed += batch[2]
        objects += batch[3]

    queued = await find_subject_queued_runs(organization_id, subject)
    queued_in_flight = [
        row for row in queued if row.state == QUEUED_RUN_IN_FLIGHT_STATE
    ]
    queued_deleted, queued_cleared = await db_client.erase_queued_runs(
        organization_id=organization_id,
        queued_run_ids=[
            row.id for row in queued if row.state != QUEUED_RUN_IN_FLIGHT_STATE
        ],
    )

    lists = await _erase_from_campaign_lists(organization_id, subject, resolve_storage)

    logger.info(
        f"Erased data for a caller of organization {organization_id}: "
        f"{len(erased)} calls ({len(in_progress)} in progress, {len(failed)} "
        f"failed), {objects} objects, {queued_deleted} queued contacts deleted, "
        f"{queued_cleared} cleared, {lists.rows_removed} rows from "
        f"{lists.rewritten} contact lists ({len(lists.failed)} failed)"
    )
    return SubjectErasureResponse(
        number=subject.canonical,
        calls_erased=len(erased),
        calls_in_progress=in_progress,
        calls_failed=failed,
        objects_deleted=objects,
        queued_calls_deleted=queued_deleted,
        queued_calls_cleared=queued_cleared,
        queued_calls_in_progress=len(queued_in_flight),
        campaign_lists_rewritten=lists.rewritten,
        campaign_list_rows_removed=lists.rows_removed,
        campaign_lists_failed=lists.failed,
    )
