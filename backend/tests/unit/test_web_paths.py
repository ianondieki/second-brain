"""Every web page the backend links to (in-app notices, emails, redirects) is a page of the web app.

The route table is read from ``frontend/app``: each ``page.tsx`` is a route, route groups ``(name)`` are left out and
``[param]`` is one path segment. The backend's links are read from its source: every string or f-string that is a
site path (``"/dev/ideas/{id}"``, ``"/org/inbox?org={org}&tab=matches"``) or a base URL followed by one
(``f"{base}/verify/{cert_id}"``), except the API's own paths (``/api/...``, router decorators). The query and fragment
are ignored and ``{...}`` stands for one segment. A path the web app has no page for fails unless it is listed below
with the reason. Until the random-handle branch, every tracker notice and two emails linked to ``/engagements/{id}``
and the reminders to ``/engagements``: no page (P10-F open item 2 and its follow-up).
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from bridge.models.enums import EngagementParty
from bridge.web_paths import DEV_ENGAGEMENTS, ORG_ENGAGEMENTS, engagement_path, org_engagements_path

REPO = Path(__file__).resolve().parents[3]
APP = REPO / "frontend" / "app"
SRC = REPO / "backend" / "src" / "bridge"
BASE_URL = re.compile(r"\bbase\b|base_url")  # f"{base}/…", f"{settings.public_base_url.rstrip('/')}/…"

# Site paths in the backend that are not links to the web app.
NOT_PAGES = {
    "/chat/completions": "an OpenAI-compatible provider's API (llm/openai_adapter.py)",
    "/email": "Postmark's API, after its base URL (notifications/email.py)",
    "/nda": "a request path's ending that proposals/access.py tests",
    "/assistant": "a request path's segment that proposals/access.py tests",
    "/{}": "a tracker command the demo seed posts to the API (seed/demo/engagements.py)",
}
# Links to pages this branch's web app does not have: each is a known gap, reported, never a new one. Empty from P16
# (which built /settings/notifications and /help, every email footer) until P22-B's backend landed before its screens
# (P22-BF), which built the event page N27 links to; P22-C's backend lands before its screens (P22-CF builds both
# pages). An entry that has become a page fails the test, so the list never goes stale.
PAGES_NOT_BUILT: dict[str, str] = {
    "/dev/teams": "N28's link (web_paths.DEV_TEAMS): the invitations and threads page, P22-CF's",
    "/dev/teams/{}": "N29's link (web_paths.team_thread_path): one team thread's page, P22-CF's",
}


def routes() -> list[re.Pattern[str]]:
    found = []
    for page in APP.rglob("page.tsx"):
        segments = [s for s in page.parent.relative_to(APP).parts if not re.fullmatch(r"\(.*\)|@.*", s)]
        pattern = "".join(
            "/.+" if s.startswith("[...") else "/[^/]+" if s.startswith("[") else "/" + re.escape(s) for s in segments
        )
        found.append(re.compile(f"{pattern or '/'}"))
    return found


def normalise(path: str) -> str:
    path = re.split(r"[?#]", path, maxsplit=1)[0]
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"


def site_path(node: ast.AST) -> str | None:
    """The site path a string or f-string holds, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = node.value
    elif isinstance(node, ast.JoinedStr):
        parts = [str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values]
        first = node.values[0] if node.values else None
        if isinstance(first, ast.FormattedValue) and BASE_URL.search(ast.unparse(first.value)):
            parts = parts[1:]  # a base URL, then the path
        text = "".join(parts)
    else:
        return None
    if not re.match(r"/[a-z{]", text) or text.startswith("/api"):
        return None
    return normalise(text)


def backend_paths() -> dict[str, list[str]]:
    """Each normalised site path in the backend's source, with where it is written."""
    found: dict[str, list[str]] = defaultdict(list)
    for module in sorted(SRC.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        skip: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                skip.update(id(n) for d in node.decorator_list for n in ast.walk(d))  # the API's own routes
            if isinstance(node, ast.JoinedStr):
                skip.update(id(v) for v in node.values)  # read as part of the f-string
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            path = site_path(node)
            if path is not None:
                found[path].append(f"{module.relative_to(SRC)}:{getattr(node, 'lineno', '?')}")
    return found


def is_page(path: str, table: list[re.Pattern[str]]) -> bool:
    concrete = path.replace("{}", "x")
    return any(route.fullmatch(concrete) for route in table)


def test_the_route_table_is_read() -> None:
    table = routes()
    assert len(table) > 10, APP
    for page in ("/", "/dev/engagements/x", "/org/engagements/x", "/org/engagements", "/verify/x", "/login"):
        assert is_page(page, table), page
    assert not is_page("/engagements/x", table)
    assert not is_page("/engagements", table)


def test_the_scan_finds_the_links_the_backend_builds() -> None:
    found = backend_paths()
    for path in ("/dev/engagements", "/org/engagements", "/dev/ideas/{}", "/verify/{}", "/auth/link", "/login"):
        assert path in found, path
    assert site_path(ast.parse('f"{base}/engagements/{facts.engagement_id}"', mode="eval").body) == "/engagements/{}"
    assert site_path(ast.parse('f"{PREFIX}/history"', mode="eval").body) is None  # an API prefix, not a base URL


def test_every_page_the_backend_links_to_is_a_page_of_the_web_app() -> None:
    table = routes()
    found = backend_paths()
    broken = {
        path: where
        for path, where in found.items()
        if not is_page(path, table) and path not in NOT_PAGES and path not in PAGES_NOT_BUILT
    }
    assert broken == {}
    assert set(NOT_PAGES) <= set(found)  # every exception is still written somewhere
    assert set(PAGES_NOT_BUILT) <= set(found)


def test_no_page_is_listed_as_not_built() -> None:
    """A listed gap that the web app now has a page for is a stale entry: drop it from ``PAGES_NOT_BUILT``."""
    table = routes()
    assert [path for path in PAGES_NOT_BUILT if is_page(path, table)] == []


def test_the_email_footers_and_the_upgrade_link_are_pages() -> None:
    """Every email footer's "Manage notifications" and "Help", and the 402's upgrade link (P16, P14-F)."""
    table = routes()
    found = backend_paths()
    for path in ("/settings/notifications", "/help", "/billing/upgrade", "/org/inbox/matches/{}"):
        assert path in found, path
        assert is_page(path, table), path


def test_each_party_opens_an_engagement_in_its_own_portal() -> None:
    table = routes()
    engagement, org = uuid4(), uuid4()
    developer = engagement_path(EngagementParty.DEVELOPER, engagement)
    organisation = engagement_path(EngagementParty.ORG, engagement)
    assert (developer, organisation) == (f"/dev/engagements/{engagement}", f"/org/engagements/{engagement}")
    assert org_engagements_path(org) == f"/org/engagements?org={org}"
    for link in (developer, organisation, org_engagements_path(org), DEV_ENGAGEMENTS, ORG_ENGAGEMENTS):
        assert is_page(normalise(link), table), link
