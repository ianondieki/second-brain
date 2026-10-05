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
MAX_PATH_CHARS: Final = 500  # in_app_notifications.link (bridge.notifications.in_app.MAX_LINK_CHARS)


def engagement_path(party: EngagementParty, engagement_id: UUID) -> str:
    """One engagement's tracker in ``party``'s portal."""
    portal = DEV_ENGAGEMENTS if party is EngagementParty.DEVELOPER else ORG_ENGAGEMENTS
    return f"{portal}/{engagement_id}"


def messages_path(party: EngagementParty, engagement_id: UUID) -> str:
    """One engagement's Messages route in ``party``'s portal, landing on the thread's heading (N18)."""
    return f"{engagement_path(party, engagement_id)}/messages#messages-heading"


def org_engagements_path(org_id: UUID) -> str:
    """The organisation's engagements list, for that organisation."""
    return f"{ORG_ENGAGEMENTS}?org={org_id}"


def discover_path(view: str, *, niche: str | None, county: str | None, words: str | None) -> str:
    """Discover on ``view`` with the filters applied, as the web app's ``discoverHref`` writes it (the default view,
    ``problems``, left out; ``view``, ``niche``, ``county``, then ``words``). Words that would take the path over
    ``MAX_PATH_CHARS`` (an in-app notification's link) are left out: the view and the other filters still apply."""
    params = [("view", view)] if view != "problems" else []
    params += [(key, value) for key, value in (("niche", niche), ("county", county)) if value]
    if words:
        with_words = f"{DEV_DISCOVER}?{urlencode([*params, ('words', words)])}"
        if len(with_words) <= MAX_PATH_CHARS:
            return with_words
    return f"{DEV_DISCOVER}?{urlencode(params)}" if params else DEV_DISCOVER
