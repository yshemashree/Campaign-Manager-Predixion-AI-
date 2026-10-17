"""Request/response shapes for agents, connections, campaigns, cohorts and contacts."""

import re
import uuid
from datetime import datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.cohort_schema import RESERVED_COLUMNS, VARIABLE_NAME_RE, VARIABLE_TYPES
from app.domain.retry_policy import DEFAULT_RETRY_POLICY
from app.domain.states import TERMINAL_CONTACT_STATUSES, LifecycleAction

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- agents ----------


class AgentVariable(BaseModel):
    name: str
    type: Literal["string", "number", "integer", "boolean", "date", "enum"] = "string"
    required: bool = True
    example: str = ""
    allowed: list[str] = []
    max_length: int = Field(default=1000, ge=1, le=10_000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not VARIABLE_NAME_RE.fullmatch(v):
            raise ValueError(
                "use lowercase letters, digits and underscores, starting with a letter"
            )
        if v in RESERVED_COLUMNS:
            raise ValueError(f"'{v}' is a reserved column name")
        return v

    @model_validator(mode="after")
    def _enum_needs_values(self) -> "AgentVariable":
        if self.type == "enum" and not self.allowed:
            raise ValueError("enum variables need a list of allowed values")
        assert self.type in VARIABLE_TYPES
        return self


class AgentBase(BaseModel):
    variables: list[AgentVariable] = []
    initial_bot_message: str | None = Field(default=None, max_length=2000)
    initial_state_name: str | None = Field(default=None, max_length=200)

    @field_validator("variables")
    @classmethod
    def _unique(cls, v: list[AgentVariable]) -> list[AgentVariable]:
        names = [x.name for x in v]
        if len(names) != len(set(names)):
            raise ValueError("variable names must be unique")
        return v


class AgentCreate(AgentBase):
    name: str = Field(min_length=2, max_length=200)
    app_id: str = Field(min_length=1, max_length=200)
    app_version: int = Field(ge=1)


class AgentUpdate(AgentBase):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    app_id: str | None = Field(default=None, min_length=1, max_length=200)
    app_version: int | None = Field(default=None, ge=1)
    variables: list[AgentVariable] | None = None  # type: ignore[assignment]


class AgentOut(Out):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    app_id: str
    app_version: int
    variables: list[AgentVariable]
    initial_bot_message: str | None
    initial_state_name: str | None
    created_at: datetime


# ---------- connections ----------


def _check_numbers(numbers: list[str]) -> list[str]:
    bad = [n for n in numbers if not E164_RE.fullmatch(n)]
    if bad:
        raise ValueError(f"not in +E.164 format: {', '.join(bad)}")
    if len(set(numbers)) != len(numbers):
        raise ValueError("caller numbers must be unique")
    return numbers


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    connection_id: str = Field(min_length=1, max_length=200)
    caller_numbers: list[str] = Field(min_length=1, max_length=100)

    @field_validator("caller_numbers")
    @classmethod
    def _numbers(cls, v: list[str]) -> list[str]:
        return _check_numbers(v)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    connection_id: str | None = Field(default=None, min_length=1, max_length=200)
    caller_numbers: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("caller_numbers")
    @classmethod
    def _numbers(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_numbers(v)


class ConnectionOut(Out):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    connection_id: str
    caller_numbers: list[str]
    created_at: datetime


# ---------- campaigns ----------


class RetryRule(BaseModel):
    enabled: bool = True
    delay_s: int = Field(default=600, ge=0, le=7 * 24 * 3600)


class RetryRules(BaseModel):
    busy: RetryRule = RetryRule(**DEFAULT_RETRY_POLICY["rules"]["busy"])
    no_answer: RetryRule = RetryRule(**DEFAULT_RETRY_POLICY["rules"]["no_answer"])
    short_call: RetryRule = RetryRule(**DEFAULT_RETRY_POLICY["rules"]["short_call"])
    failed: RetryRule = RetryRule(**DEFAULT_RETRY_POLICY["rules"]["failed"])


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    short_call_threshold_s: int = Field(default=10, ge=0, le=600)
    backoff: float = Field(default=1.0, ge=1.0, le=5.0)
    rules: RetryRules = RetryRules()


class CallingWindowIn(BaseModel):
    timezone: str = "Asia/Kolkata"
    days: list[int] = Field(default=[1, 2, 3, 4, 5, 6], min_length=1, max_length=7)
    start: str = "09:00"
    end: str = "21:00"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone, use an IANA name like Asia/Kolkata") from exc
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("days are 1 (Monday) to 7 (Sunday)")
        return sorted(set(v))

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("use HH:MM, e.g. 09:00")
        time.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _order(self) -> "CallingWindowIn":
        if time.fromisoformat(self.start) >= time.fromisoformat(self.end):
            raise ValueError(
                "the window must start before it ends (overnight windows are not supported)"
            )
        return self


class AppOverrides(BaseModel):
    initial_bot_message: str | None = Field(default=None, max_length=2000)
    initial_state_name: str | None = Field(default=None, max_length=200)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    agent_id: uuid.UUID
    connection_id: uuid.UUID
    # Defaults to every number on the connection.
    caller_numbers: list[str] | None = None
    attempts_per_second: float = Field(default=1.0, ge=0.1, le=500)
    retry_policy: RetryPolicy = RetryPolicy()
    calling_window: CallingWindowIn = CallingWindowIn()
    start_at: datetime | None = None
    end_at: datetime | None = None
    app_overrides: AppOverrides = AppOverrides()

    @model_validator(mode="after")
    def _times(self) -> "CampaignCreate":
        for name in ("start_at", "end_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must include a timezone, e.g. 2026-11-01T09:00:00+05:30")
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    # agent_id, connection_id and caller_numbers can only change while the campaign is a draft.
    agent_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    caller_numbers: list[str] | None = None
    attempts_per_second: float | None = Field(default=None, ge=0.1, le=500)
    retry_policy: RetryPolicy | None = None
    calling_window: CallingWindowIn | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    app_overrides: AppOverrides | None = None


class CampaignOut(Out):
    id: uuid.UUID
    org_id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    connection_id: uuid.UUID
    name: str
    status: str
    state_version: int
    pause_reason: str | None
    attempts_per_second: float
    caller_numbers: list[str]
    retry_policy: dict[str, Any]
    calling_window: dict[str, Any]
    start_at: datetime | None
    end_at: datetime | None
    app_overrides: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    contact_counts: dict[str, int] = {}  # contacts by status, e.g. {"pending": 3}


class StatusAction(BaseModel):
    action: LifecycleAction


class CampaignStats(BaseModel):
    campaign_id: uuid.UUID
    status: str
    total: int
    by_status: dict[str, int]
    attempts_total: int
    in_window: bool
    window_closes_at: datetime | None
    next_window_opens_at: datetime | None


# ---------- cohorts & contacts ----------


class CohortOut(Out):
    id: uuid.UUID
    campaign_id: uuid.UUID
    filename: str
    rows_total: int
    rows_accepted: int
    rows_rejected: int
    rows_duplicate: int
    created_at: datetime


class RowErrorOut(BaseModel):
    row: int
    column: str
    message: str


class CohortUploadResult(BaseModel):
    dry_run: bool
    accepted: bool
    cohort: CohortOut | None = None
    rows_total: int
    rows_valid: int
    rows_rejected: int
    duplicates_in_file: int
    duplicates_existing: int
    dnd_skipped: int = 0  # valid rows left out because the number is on the DND list
    header_errors: list[str]
    errors: list[RowErrorOut]  # first 100; the full list is in the error report
    error_report_csv: str | None = None  # every rejected row with its reason, as CSV


class ContactOut(Out):
    id: uuid.UUID
    campaign_id: uuid.UUID
    phone_e164: str
    lead_id: str
    variables: dict[str, Any]
    status: str
    attempts_made: int
    next_attempt_at: datetime | None  # null once the contact is finished
    last_outcome: str | None
    final_reason: str | None
    updated_at: datetime

    @model_validator(mode="after")
    def _no_next_when_done(self) -> "ContactOut":
        if self.status in TERMINAL_CONTACT_STATUSES:
            self.next_attempt_at = None
        return self


class AttemptOut(Out):
    id: uuid.UUID
    attempt_no: int
    status: str
    from_number: str | None
    provider_attempt_id: str | None
    http_status: int | None
    created_at: datetime
    dispatched_at: datetime | None
    ended_at: datetime | None
    duration_s: int | None
    failure_reason: str | None


class ContactDetail(ContactOut):
    attempts: list[AttemptOut]


class ContactPage(BaseModel):
    items: list[ContactOut]
    next_cursor: str | None
    total: int  # contacts matching the filters, across all pages
