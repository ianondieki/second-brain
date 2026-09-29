"""The Tier-2 HTML render and its marks (REQ-PROV-03, REQ-REPO-01; docs/spec/06 6.1, 6.4 item 3): the tiled overlay
and the metadata carry the viewer's name, organisation, EAT date and view id; the owner attribution carries the handle
(or name), the certificate id, the EAT registration time and the /verify link; every value is escaped and the page
runs no script."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from typing import Any

from bridge.ids import uuid7
from bridge.proposals.render import HEADERS, OWNER_NOTE, STYLE, TILES, OwnerMark, ViewerMark, mark_text, render_document

VIEW_ID = uuid7()
OWNER = OwnerMark(
    name="dev-cold-chain",
    cert_id="Ab3dEf6hJk",
    registered_at=datetime(2026, 9, 28, 21, 30, tzinfo=UTC),  # 2026-09-29 00:30 in Nairobi
    verify_url="https://bridge.example.test/verify/Ab3dEf6hJk",
)
VIEWER = ViewerMark(
    name="Rita Reviewer",
    org_name="Buyer Limited",
    view_id=VIEW_ID,
    viewed_at=datetime(2026, 9, 29, 9, 5, 7, tzinfo=UTC),  # 12:05 EAT
)
DOCUMENT = {
    "format": "bridge-tier2-v1",
    "approach": "LoRa mesh relays\nevery 90 s",
    "architecture": None,
    "pricing": "KES 25,000 setup",
    "notes": "   ",
    "links": ["https://demo.example.test/walkthrough", "javascript:alert(1)"],
    "attachments": [{"id": str(uuid7()), "file_name": "deck.pdf", "object_key": "attachments/secret/key"}],
}


def page(viewer: ViewerMark = VIEWER, document: Mapping[str, Any] | None = None, title: str = "Cold-chain") -> str:
    return render_document(title=title, document=document or DOCUMENT, owner=OWNER, viewer=viewer)


def test_the_overlay_and_the_metadata_carry_the_viewer_mark() -> None:
    html = page()
    line = "Rita Reviewer · Buyer Limited · 2026-09-29 12:05 EAT · view " + str(VIEW_ID)
    assert mark_text(VIEWER) == line
    overlay = re.search(r'<div class="overlay" aria-hidden="true">(.*?)</div>', html)
    assert overlay is not None
    assert overlay.group(1) == f"<span>{line}</span>" * TILES
    assert f'<meta name="bridge:view-id" content="{VIEW_ID}">' in html
    assert '<meta name="bridge:viewer" content="Rita Reviewer">' in html
    assert '<meta name="bridge:viewer-org" content="Buyer Limited">' in html
    assert '<meta name="bridge:viewed-on" content="2026-09-29 12:05:07 EAT">' in html
    assert '<meta name="bridge:cert-id" content="Ab3dEf6hJk">' in html
    assert f'<p class="mark">{line}.' in html  # and once more in plain text at the end


def test_the_owner_attribution_names_the_handle_certificate_time_and_verify_link() -> None:
    html = page()
    assert "By dev-cold-chain · Certificate Ab3dEf6hJk · Registered 2026-09-29 00:30:00 EAT" in html
    assert 'href="https://bridge.example.test/verify/Ab3dEf6hJk"' in html


def test_the_verify_link_opens_outside_the_frame() -> None:
    # The web app shows the page in a sandboxed iframe that lets popups escape; /verify refuses to be framed
    # (X-Frame-Options: DENY), so the link must open a new top-level tab, with no opener and no referrer.
    html = page()
    link = re.search(r"<a ([^>]*)>Verify this record</a>", html)
    assert link is not None
    attributes = link.group(1)
    assert 'href="https://bridge.example.test/verify/Ab3dEf6hJk"' in attributes
    assert 'target="_blank"' in attributes
    assert 'rel="noopener noreferrer nofollow"' in attributes


def test_tier2_sections_links_and_attachment_names_but_never_object_keys() -> None:
    html = page()
    assert '<h2>Approach</h2><div class="text">LoRa mesh relays\nevery 90 s</div>' in html
    assert "<h2>Pricing</h2>" in html
    assert "<h2>Architecture</h2>" not in html  # empty fields are left out
    assert "<h2>Notes</h2>" not in html
    assert '<a href="https://demo.example.test/walkthrough" rel="noopener noreferrer nofollow"' in html
    assert "<li>javascript:alert(1)</li>" in html  # shown as text, never a link
    assert 'href="javascript' not in html
    assert "<li>deck.pdf</li>" in html
    assert "attachments/secret/key" not in html


def test_every_value_is_escaped_and_no_script_runs() -> None:
    hostile = ViewerMark(
        name="<script>alert('n')</script>",
        org_name='"><img src=x onerror=alert(1)>',
        view_id=VIEW_ID,
        viewed_at=VIEWER.viewed_at,
    )
    document = DOCUMENT | {"approach": "</div><script>alert(2)</script>", "links": ['https://x.test/"onmouseover=a']}
    html = page(hostile, document, title="<b>Title</b>")
    assert "<script" not in html
    assert "<img" not in html
    assert "<b>Title</b>" not in html
    assert "&lt;script&gt;alert(&#x27;n&#x27;)&lt;/script&gt;" in html
    assert 'content="&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in html
    assert 'href="https://x.test/&quot;onmouseover=a"' in html


def test_the_owner_preview_has_no_view_id() -> None:
    html = page(ViewerMark(name="Dev Owner", org_name=None, view_id=None, viewed_at=VIEWER.viewed_at))
    assert "bridge:view-id" not in html
    assert '<meta name="bridge:render" content="owner-preview">' in html
    assert "Dev Owner · owner preview · 2026-09-29 12:05 EAT</span>" in html
    assert escape(OWNER_NOTE) in html


def test_the_headers_forbid_caching_and_allow_only_the_stylesheet() -> None:
    assert "no-store" in HEADERS["Cache-Control"]
    assert "no-cache" in HEADERS["Cache-Control"]
    assert HEADERS["Pragma"] == "no-cache"
    digest = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    csp = HEADERS["Content-Security-Policy"]
    assert csp.startswith("default-src 'none';")
    assert f"style-src 'sha256-{digest}'" in csp
    assert "script-src" not in csp  # default-src 'none' forbids every script
    assert f"<style>{STYLE}</style>" in page()
