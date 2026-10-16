"""Database tables.

Every model inherits from `Base`. Alembic compares `Base.metadata` against the live database
to generate migrations, so every model module is imported here.
"""

from app.models.base import Base
from app.models.campaigns import (
    Agent,
    CallAttempt,
    Campaign,
    Cohort,
    Connection,
    Contact,
    WebhookEvent,
)
from app.models.dnd import DndNumber
from app.models.tenancy import Organization, User, Workspace, WorkspaceMember

__all__ = [
    "Agent",
    "Base",
    "CallAttempt",
    "Campaign",
    "Cohort",
    "Connection",
    "Contact",
    "DndNumber",
    "Organization",
    "User",
    "WebhookEvent",
    "Workspace",
    "WorkspaceMember",
]
