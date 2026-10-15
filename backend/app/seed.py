"""Create the first superadmin, plus demo data for local runs: `python -m app.seed`.

Idempotent: running it again changes nothing. Docker compose runs it after migrations.

Demo logins (local only):
    superadmin   admin@example.com / admin12345        (from SEED_SUPERADMIN_*)
    org admin    admin@acme.example.com   / acme12345
    member       agent@acme.example.com   / acme12345
"""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging, get_logger
from app.core.security import encrypt_secret, hash_password
from app.domain.states import Role
from app.models import Agent, Connection, Organization, User, Workspace, WorkspaceMember

log = get_logger("seed")


async def _user(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def seed(session: AsyncSession, settings: Settings) -> None:
    if await _user(session, settings.seed_superadmin_email) is None:
        session.add(
            User(
                email=settings.seed_superadmin_email.lower(),
                full_name="Platform Admin",
                password_hash=hash_password(settings.seed_superadmin_password),
                role=Role.SUPERADMIN,
            )
        )
        log.info("seeded_superadmin", email=settings.seed_superadmin_email)

    if (
        settings.seed_demo_data
        and await session.scalar(select(Organization).where(Organization.name == "Acme Lending"))
        is None
    ):
        org = Organization(
            name="Acme Lending",
            sarvam_org_id="acme-org",
            max_concurrent_calls=20,
            max_calls_per_second=5,
        )
        session.add(org)
        await session.flush()
        ws = Workspace(
            org_id=org.id,
            name="Collections",
            sarvam_workspace_id="acme-collections",
            sarvam_api_key_enc=encrypt_secret(settings, "demo-api-key-1234"),
            sarvam_api_key_last4="1234",
        )
        session.add(ws)
        await session.flush()
        admin = User(
            email="admin@acme.example.com",
            full_name="Acme Admin",
            password_hash=hash_password("acme12345"),
            role=Role.ORG_ADMIN,
            org_id=org.id,
        )
        member = User(
            email="agent@acme.example.com",
            full_name="Acme Campaign Owner",
            password_hash=hash_password("acme12345"),
            role=Role.MEMBER,
            org_id=org.id,
        )
        session.add_all([admin, member])
        await session.flush()
        session.add(WorkspaceMember(user_id=member.id, workspace_id=ws.id))
        session.add(
            Agent(
                org_id=org.id,
                workspace_id=ws.id,
                name="EMI Reminder",
                app_id="emi-reminder-app",
                app_version=7,
                variables=[
                    {
                        "name": "customer_name",
                        "type": "string",
                        "required": True,
                        "example": "Priya",
                    },
                    {"name": "emi_amount", "type": "number", "required": True, "example": "4500"},
                    {"name": "due_date", "type": "date", "required": True, "example": "2026-11-05"},
                    {
                        "name": "language",
                        "type": "enum",
                        "required": False,
                        "allowed": ["en", "hi", "ta"],
                        "example": "en",
                    },
                ],
                initial_bot_message="Hello {customer_name}, this is a reminder from Acme Lending.",
            )
        )
        session.add(
            Connection(
                org_id=org.id,
                workspace_id=ws.id,
                name="Main line",
                connection_id="acme-conn-1",
                caller_numbers=["+918069000001", "+918069000002", "+918069000003"],
            )
        )
        log.info("seeded_demo_org", org="Acme Lending")
    await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            await seed(session, settings)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
