"""Database tables.

Every model inherits from `Base`. Alembic compares `Base.metadata` against the live database
to generate migrations, so a model only counts once it is imported here.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Predictable constraint and index names (e.g. uq_contacts_campaign_id) instead of
# database-generated ones, so migrations can refer to them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
