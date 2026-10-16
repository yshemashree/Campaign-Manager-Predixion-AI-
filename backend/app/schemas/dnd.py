"""Request/response shapes for the per-organisation Do Not Disturb list."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.campaigns import Out


class DndOut(Out):
    id: uuid.UUID
    phone_e164: str
    reason: str | None
    created_at: datetime
    created_by: uuid.UUID | None


class DndPage(BaseModel):
    items: list[DndOut]
    next_cursor: str | None
    total: int


class DndAdd(BaseModel):
    phone_numbers: list[str] = Field(min_length=1, max_length=10_000)
    reason: str | None = Field(default=None, max_length=500)


class DndAddResult(BaseModel):
    added: int
    already_listed: int
    invalid: list[str]  # the inputs that aren't valid phone numbers, as sent
