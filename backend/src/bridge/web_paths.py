"""The web app's engagement pages that in-app notices and emails link to (frontend ``app/(app)/{dev,org}/engagements``),
and Discover with a saved search's filters (frontend ``app/(app)/dev/discover``, whose ``discoverHref`` writes the
same query).

Each party opens an engagement in its own portal: the developer under ``/dev/engagements``, an organisation's people
under ``/org/engagements``. There is no shared ``/engagements`` page. One engagement's organisation page reads the
organisation from the engagement itself, so it needs no ``?org=``; the organisation's list shows the organisation
named by ``?org=`` (else the member's first), so a link to it names the organisation. ``tests/unit/test_web_paths.py``
checks every page path the backend writes against the frontend's route table.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlencode
from uuid import UUID

from bridge.models.enums import EngagementParty

DEV_ENGAGEMENTS: Final = "/dev/engagements"
ORG_ENGAGEMENTS: Final = "/org/engagements"
DEV_DISCOVER: Final = "/dev/discover"


def engagement_path(party: EngagementParty, engagement_id: UUID) -> str:
    """One engagement's tracker in ``party``'s portal."""
    portal = DEV_ENGAGEMENTS if party is EngagementParty.DEVELOPER else ORG_ENGAGEMENTS
    return f"{portal}/{engagement_id}"


def org_engagements_path(org_id: UUID) -> str:
    """The organisation's engagements list, for that organisation."""
    return f"{ORG_ENGAGEMENTS}?org={org_id}"


def discover_path(view: str, *, niche: str | None, county: str | None, words: str | None) -> str:
    """Discover on ``view`` with the filters applied, as the web app's ``discoverHref`` writes it (the default view,
    ``problems``, left out; ``view``, ``niche``, ``county``, then ``words``)."""
    params = [("view", view)] if view != "problems" else []
    params += [(key, value) for key, value in (("niche", niche), ("county", county), ("words", words)) if value]
    query = urlencode(params)
    return f"{DEV_DISCOVER}?{query}" if query else DEV_DISCOVER
