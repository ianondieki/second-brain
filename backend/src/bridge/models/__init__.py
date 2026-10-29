"""ORM models. Importing this package registers every table on ``Base.metadata`` (Alembic and the RLS test read it).

Every table declares ``info={"tenancy": ...}`` (see ``bridge.models.base.Tenancy``); the RLS test fails for a table
that does not, so a new org- or user-scoped table cannot ship without a policy.
"""

from bridge.models.base import Base, Tenancy

__all__ = ["Base", "Tenancy"]
