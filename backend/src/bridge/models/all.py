"""Import every model module so ``Base.metadata`` is complete (used by Alembic, the seed and the RLS test)."""

from __future__ import annotations

from bridge.admin import models as admin_models
from bridge.audit import models as audit_models
from bridge.auth import models as auth_models
from bridge.billing import models as billing_models
from bridge.directory import models as directory_models
from bridge.engagements import models as engagement_models
from bridge.legal import models as legal_models
from bridge.llm import models as llm_models
from bridge.matching import models as matching_models
from bridge.notifications import models as notification_models
from bridge.problems import models as problem_models
from bridge.profiles import models as profile_models
from bridge.proposals import models as proposal_models
from bridge.provenance import models as provenance_models
from bridge.tenancy import models as tenancy_models

MODULES = (
    admin_models,
    audit_models,
    auth_models,
    billing_models,
    directory_models,
    engagement_models,
    legal_models,
    llm_models,
    matching_models,
    notification_models,
    problem_models,
    profile_models,
    proposal_models,
    provenance_models,
    tenancy_models,
)
