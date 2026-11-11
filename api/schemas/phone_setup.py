"""Request/response schemas for an agent's phone setup and LightMove numbers."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

SetupMethod = Literal["keep_existing", "new_number", "mobile"]
ForwardWhen = Literal["no_answer", "busy", "all", "outside_hours"]
NumberKind = Literal["local", "mobile"]


class PhoneSetupChoice(BaseModel):
    method: SetupMethod
    forward_when: Optional[ForwardWhen] = None
    started_at: datetime


class PhoneSetupCheck(BaseModel):
    """Whether the number has had a call since the setup was chosen.

    ``waiting`` until the first inbound call to this number reaches the agent;
    ``received`` after. ``not_started`` when no setup has been chosen yet.
    """

    status: Literal["not_started", "waiting", "received"]
    first_call_at: Optional[datetime] = None
    first_call_run_id: Optional[int] = None
    # Only when the carrier passed the forwarding number on (Twilio
    # ``ForwardedFrom``); most calls won't have it.
    forwarded_from: Optional[str] = None


class AgentPhoneNumber(BaseModel):
    id: int
    telephony_configuration_id: int
    address: str
    address_normalized: str
    label: Optional[str] = None
    provider: str
    provider_name: str
    is_active: bool
    provider_inactive: bool
    # Bought by LightMove on its own provider account.
    lightmove_number: bool
    setup: Optional[PhoneSetupChoice] = None
    check: PhoneSetupCheck


class PhoneSetupResponse(BaseModel):
    # False when this deployment has no platform provider account configured;
    # the "LightMove provides the number" option then shows "Coming soon".
    platform_numbers_available: bool
    numbers: List[AgentPhoneNumber]


class PhoneSetupUpdateRequest(BaseModel):
    phone_number_id: int
    method: SetupMethod
    forward_when: Optional[ForwardWhen] = None


class AvailablePlatformNumber(BaseModel):
    phone_number: str
    friendly_name: str
    kind: NumberKind
    locality: Optional[str] = None
    region: Optional[str] = None


class AvailablePlatformNumbersResponse(BaseModel):
    country: str
    numbers: List[AvailablePlatformNumber]


class PlatformNumberPurchaseRequest(BaseModel):
    phone_number: str = Field(..., min_length=4, max_length=32)
