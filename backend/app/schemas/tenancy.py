"""Request/response shapes for auth, organisations, workspaces and users."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(Out):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    org_id: uuid.UUID | None
    is_active: bool
    workspace_ids: list[uuid.UUID] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sarvam_org_id: str | None = Field(default=None, max_length=200)
    max_concurrent_calls: int = Field(default=5, ge=1, le=1000)
    max_calls_per_second: int = Field(default=5, ge=1, le=500)
    # Optionally create the organisation's first admin in the same call.
    admin_email: EmailStr | None = None
    admin_password: str | None = Field(default=None, min_length=8)
    admin_name: str = ""


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    sarvam_org_id: str | None = Field(default=None, max_length=200)
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=1000)
    max_calls_per_second: int | None = Field(default=None, ge=1, le=500)
    is_active: bool | None = None


class OrganizationOut(Out):
    id: uuid.UUID
    name: str
    sarvam_org_id: str | None
    max_concurrent_calls: int
    max_calls_per_second: int
    limit_version: int
    is_active: bool
    created_at: datetime


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sarvam_workspace_id: str | None = Field(default=None, max_length=200)
    # Write-only: stored encrypted, never returned.
    sarvam_api_key: str | None = Field(default=None, min_length=4, max_length=500)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    sarvam_workspace_id: str | None = Field(default=None, max_length=200)
    sarvam_api_key: str | None = Field(default=None, min_length=4, max_length=500)


class WorkspaceOut(Out):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    sarvam_workspace_id: str | None
    sarvam_api_key_last4: str | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(default="", max_length=200)
    role: Literal["org_admin", "member"] = "member"
    workspace_ids: list[uuid.UUID] = []
    # Superadmins must say which organisation the user belongs to.
    org_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: Literal["org_admin", "member"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    workspace_ids: list[uuid.UUID] | None = None
