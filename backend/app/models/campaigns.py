"""Agents, connections, campaigns, cohorts, contacts, call attempts and webhook events."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.models.base import Base, TimestampMixin, utcnow


class Agent(TimestampMixin, Base):
    """A Sarvam voice agent registered in our system (we can't fetch agents from Sarvam)."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    app_id: Mapped[str] = mapped_column(String(200))
    app_version: Mapped[int] = mapped_column(Integer)
    # [{"name": "customer_name", "type": "string", "required": true, "example": "Priya"}, ...]
    variables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    initial_bot_message: Mapped[str | None] = mapped_column(Text)
    initial_state_name: Mapped[str | None] = mapped_column(String(200))


class Connection(TimestampMixin, Base):
    """A Sarvam telephony connection and the caller numbers available on it."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    connection_id: Mapped[str] = mapped_column(String(200))
    caller_numbers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # Bumped on every lifecycle change; the Redis gate rejects writes and sends from older versions.
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    pause_reason: Mapped[str | None] = mapped_column(String(50))
    attempts_per_second: Mapped[float] = mapped_column(Float, default=1.0)
    caller_numbers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # {"timezone": "Asia/Kolkata", "days": [1,2,3,4,5], "start": "09:00", "end": "18:00"}
    calling_window: Mapped[dict[str, Any]] = mapped_column(JSONB)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    app_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Cohort(TimestampMixin, Base):
    """One uploaded CSV."""

    __tablename__ = "cohorts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    error_report: Mapped[str | None] = mapped_column(Text)  # CSV of rejected rows
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Contact(TimestampMixin, Base):
    """One person to call. This table is also the dispatch queue."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164"),
        # THE QUEUE INDEX: only queued rows, ordered exactly like the claim query.
        Index(
            "ix_contacts_due",
            "campaign_id",
            "priority",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retry_scheduled')"),
        ),
        Index("ix_contacts_campaign_status", "campaign_id", "status"),
        Index(
            "ix_contacts_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'dialing'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    cohort_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cohorts.id", ondelete="SET NULL")
    )
    phone_e164: Mapped[str] = mapped_column(String(20))
    lead_id: Mapped[str] = mapped_column(String(200))
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    prev_status: Mapped[str | None] = mapped_column(String(20))
    # 0 = a retry that is due (served first), 1 = a fresh contact
    priority: Mapped[int] = mapped_column(SmallInteger, default=1)
    attempts_made: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outcome: Mapped[str | None] = mapped_column(String(20))
    final_reason: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CallAttempt(TimestampMixin, Base):
    """One dial. Its id is the attempt_ref we send to Sarvam and get back in the webhook."""

    __tablename__ = "call_attempts"
    __table_args__ = (
        # The last line of defence against sending the same attempt twice.
        UniqueConstraint("contact_id", "attempt_no"),
        Index(
            "ix_call_attempts_open",
            "created_at",
            postgresql_where=text("status IN ('reserved', 'dispatched', 'unknown')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    from_number: Mapped[str | None] = mapped_column(String(20))
    provider_attempt_id: Mapped[str | None] = mapped_column(String(200))
    http_status: Mapped[int | None] = mapped_column(Integer)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class WebhookEvent(Base):
    """Every webhook we receive, stored before it is processed (audit + idempotency)."""

    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)
    attempt_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
