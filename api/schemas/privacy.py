"""Request and response types for data subject requests (GDPR Art. 15 and 17)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

SUBJECT_NUMBER_MAX_LENGTH = 255


class DeleteWorkflowRunDataResponse(BaseModel):
    run_id: int
    objects_deleted: int = Field(
        description="Stored recordings and transcripts deleted for the call."
    )


class SubjectRecordingUrls(BaseModel):
    """Signed links to a call's stored files, valid for one hour."""

    recording: Optional[str] = None
    user_recording: Optional[str] = None
    bot_recording: Optional[str] = None
    transcript: Optional[str] = None


class SubjectTranscriptLine(BaseModel):
    time_from_start_seconds: float
    speaker: str
    text: str
    node_name: str = ""
    turn: int = 0


class SubjectCallData(BaseModel):
    id: int
    workflow_id: int
    workflow_name: str
    name: str
    created_at: Optional[datetime] = None
    direction: str
    status: str
    disposition: Optional[str] = None
    duration_seconds: Optional[float] = None
    in_progress: bool
    already_erased: bool
    initial_context: dict[str, Any]
    gathered_context: dict[str, Any]
    annotations: dict[str, Any]
    transcript: list[SubjectTranscriptLine]
    chat_turns: list[Any] = Field(default_factory=list)
    files: SubjectRecordingUrls


class SubjectQueuedCall(BaseModel):
    """A campaign contact row for the number: a call made or still to come."""

    id: int
    campaign_id: int
    campaign_name: str
    state: str
    created_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None
    context_variables: dict[str, Any]


class SubjectDataResponse(BaseModel):
    number: str = Field(description="The number searched for, normalized.")
    generated_at: datetime
    signed_urls_expire_in: int = Field(
        description="Seconds the links in `files` stay valid."
    )
    calls: list[SubjectCallData]
    queued_calls: list[SubjectQueuedCall]
    truncated: bool = Field(
        description="More calls matched than one export returns; the oldest are listed."
    )


class SubjectNumberRequest(BaseModel):
    number: str = Field(
        min_length=1,
        max_length=SUBJECT_NUMBER_MAX_LENGTH,
        description=(
            "The caller's phone number: international format, or national "
            "format when all your numbers are in one country."
        ),
    )


class SubjectErasureResponse(BaseModel):
    number: str = Field(description="The number erased, normalized.")
    calls_erased: int
    calls_in_progress: list[int] = Field(
        description="Calls still running, left untouched. Erase again once they end."
    )
    calls_failed: list[int] = Field(
        description="Calls whose stored files could not be deleted, left untouched."
    )
    objects_deleted: int
    queued_calls_deleted: int = Field(
        description="Campaign contacts not yet called, removed so they are never called."
    )
    queued_calls_cleared: int = Field(
        description="Campaign contact rows of calls already made, cleared."
    )
    queued_calls_in_progress: int = Field(
        description="Campaign contacts being dialled right now, left untouched."
    )
    campaign_lists_rewritten: int
    campaign_list_rows_removed: int
    campaign_lists_failed: list[int] = Field(
        description="Campaigns whose uploaded contact list could not be rewritten."
    )
