"""The server-side HTML render of a proposal's Tier 2 with its two marks (REQ-PROV-03, REQ-REPO-01; docs/spec/06 6.1,
6.4 item 3, the honest "watermark").

- **Owner attribution**: the owner's pseudonymous handle until the organisation approved to proceed
  (``INTEREST_CONFIRMED``), their display name after; the certificate id, ``registered_at`` in EAT and the link to
  ``/verify/{cert_id}``.
- **Per-viewer mark** (Release 1): a visible tiled overlay repeating the viewer's name, organisation, the EAT date and
  the ``view_id``, the same four in ``<meta name="bridge:...">`` document metadata, and a plain-text line at the end.
  The ``view_id`` is the ``document_views`` row the same request wrote, so a leaked copy traces to one view (the
  trace tool is Phase 3). The overlay deters and traces; it cannot stop a screenshot, and the page says so.

Every value is HTML-escaped; only ``http``/``https`` links become anchors. The page runs no script: the
Content-Security-Policy allows only the one stylesheet below (by hash) and fonts from the origin that serves the page
(the web app's ``/fonts``). Responses are never cached (``HEADERS``).
The owner's own preview carries no ``view_id`` (the owner's renders are not logged).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from bridge.engagements.calendar import NAIROBI

TILES: Final = 120
SECTIONS: Final = (
    ("approach", "Approach"),
    ("architecture", "Architecture"),
    ("pricing", "Pricing"),
    ("notes", "Notes"),
)
STYLE: Final = (
    # The Jacaranda palette (P20, docs/platform/design/p20-design-system.md; frontend/app/globals.css) and the app's
    # faces (D-66, D-67): Hanken Grotesk for the text and Fraunces for the titles, from the web app's own self-hosted
    # files under /fonts (frontend/public/fonts/LICENCES.md), each with the app's size-adjusted local fallback. The web
    # app frames this page in a sandbox, so its document has an opaque origin and a font fetch is a CORS request from
    # origin "null": the font files carry `Access-Control-Allow-Origin: *` (frontend/next.config.ts) and `font-src
    # 'self'` below names the web origin the page is served from (through the /api rewrite). Relative URLs resolve
    # against that origin; opened on the API's own origin the fonts 404 and the fallbacks take over. No images (the
    # lattice echo is a bloom and saffron gradient band, saffron's only use here). Text at 17 px / 1.65 on a 31 em
    # column, about 66 characters a line in Hanken Grotesk (measured in Chromium); titles at the app's scale (2 rem, and
    # 2.5 rem in a frame at least 40 rem wide; 1.5 rem), weights and tracking. The per-viewer mark keeps its ink,
    # opacity, size and tiling from before the restyles (spec 06 §6.4 item 3: it must survive a screenshot's
    # compression). Dark mode follows the embedding page: a frame's prefers-color-scheme takes the embedder's used
    # color-scheme (CSS Color Adjust), so the marked page is dark inside the dark app and light inside the light one.
    '@font-face{font-family:"Hanken Grotesk";src:url("/fonts/hanken-grotesk-v1.woff2") format("woff2");'
    "font-display:swap;font-weight:400 700}"
    '@font-face{font-family:"Fraunces";src:url("/fonts/fraunces-v1.woff2") format("woff2");font-display:swap;'
    "font-weight:500 700;unicode-range:U+0020-007E,U+2013-2014,U+2018-201A,U+201C-201E,U+2022,U+2026,U+2039-203A,"
    "U+20AC,U+2122}"
    '@font-face{font-family:"Fraunces";src:url("/fonts/fraunces-ext-v1.woff2") format("woff2");font-display:swap;'
    "font-weight:500 700;unicode-range:U+00A0-017F}"
    '@font-face{font-family:"Hanken Grotesk Fallback";src:local(Arial);ascent-override:100.88%;'
    "descent-override:30.57%;line-gap-override:0%;size-adjust:99.12%}"
    '@font-face{font-family:"Fraunces Fallback";src:local("Times New Roman");ascent-override:84.88%;'
    "descent-override:22.13%;line-gap-override:0%;size-adjust:115.22%}"
    ":root{color-scheme:light dark}"
    'body{margin:0;background:#f7f6fb;color:#1b1730;font:17px/1.65 "Hanken Grotesk","Hanken Grotesk Fallback",'
    'system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}'
    "body::before{content:'';display:block;height:6px;background:repeating-linear-gradient(-45deg,#5a3fc0 0 5px,"
    "#f4b53f 5px 10px)}"
    "main{position:relative;max-width:31em;margin:0 auto;padding:2rem 1.25rem 4rem}"
    ".label{margin:0;color:#8a5800;font-size:.875rem;font-weight:600;letter-spacing:.01em}"
    'h1,h2{font-family:"Fraunces","Fraunces Fallback",Georgia,"Times New Roman",serif;font-weight:580;'
    "font-optical-sizing:auto;letter-spacing:-.012em;text-wrap:balance;overflow-wrap:anywhere}"
    "h1{margin:.4rem 0 .75rem;font-size:2rem;font-weight:600;line-height:1.12;letter-spacing:-.02em}"
    "h2{margin:2.5rem 0 .6rem;font-size:1.5rem;line-height:1.2}"
    "@media (min-width:40rem){h1{font-size:2.5rem;line-height:1.06}}"
    ".owner,.note,.mark{color:#5e5873;font-size:.9375rem;line-height:1.55}"
    ".text{white-space:pre-wrap;overflow-wrap:anywhere;text-wrap:pretty}"
    "a{color:#5a3fc0;font-weight:600;text-decoration-thickness:1px;text-underline-offset:.2em;overflow-wrap:anywhere}"
    "ul{margin:.5rem 0;padding-left:1.25rem}li+li{margin-top:.35rem}"
    ".mark{margin-top:3rem;padding-top:1rem;border-top:1px solid #e4e1ee}"
    ".overlay{position:fixed;inset:-50%;z-index:2;display:grid;"
    "grid-template-columns:repeat(auto-fill,minmax(18rem,1fr));gap:4rem 2.5rem;padding:2rem;"
    "transform:rotate(-24deg);pointer-events:none;user-select:none;opacity:.14;color:#1b1730;font-size:.8rem;"
    "font-weight:500;letter-spacing:.03em;line-height:1.3;overflow-wrap:anywhere}"
    "::selection{background:#efebfc;color:#1b1730}"
    "@media (prefers-color-scheme:dark){body{background:#100c1d;color:#eeeaf8}"
    "body::before{background:repeating-linear-gradient(-45deg,#a996ff 0 5px,#f6c155 5px 10px)}"
    ".label{color:#f6c155}.owner,.note,.mark{color:#b5aecc}a{color:#a996ff}.mark{border-top-color:#2d2643}"
    ".overlay{color:#eeeaf8}::selection{background:#241c44;color:#eeeaf8}}"
    "@media print{.overlay{opacity:.2}}"
)
STYLE_HASH: Final = base64.b64encode(hashlib.sha256(STYLE.encode("utf-8")).digest()).decode("ascii")
HEADERS: Final = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Content-Security-Policy": (
        f"default-src 'none'; style-src 'sha256-{STYLE_HASH}'; font-src 'self'; base-uri 'none'; form-action 'none';"
        " frame-ancestors 'self'"
    ),
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}
# [[COPY-REVIEW]] the render's fixed text.
CONFIDENTIAL: Final = "Confidential · full proposal"
ATTACHMENTS_NOTE: Final = "File names only: attachments open from the owner's copy for now."
MARK_NOTE: Final = (
    "This copy is marked for you and the owner sees each view. The mark cannot stop a screenshot; it shows whose copy "
    "a leaked page came from."
)
OWNER_NOTE: Final = "Your own preview: organisations see their viewer's name and a view number here. Not logged."


@dataclass(frozen=True, slots=True)
class OwnerMark:
    name: str  # the handle, or the display name once the organisation approved to proceed
    cert_id: str
    registered_at: datetime
    verify_url: str


@dataclass(frozen=True, slots=True)
class ViewerMark:
    name: str
    org_name: str | None  # None for the owner's own preview
    view_id: UUID | None  # None for the owner's own preview (not logged)
    viewed_at: datetime


def eat(ts: datetime, *, seconds: bool = False) -> str:
    """A moment as the product writes it everywhere ("1 Oct 2026, 11:42 EAT"; docs/spec/07 item 7)."""
    local = ts.astimezone(NAIROBI)
    clock_part = local.strftime("%H:%M:%S" if seconds else "%H:%M")
    return f"{local.day} {local:%b %Y}, {clock_part} EAT"


def mark_text(viewer: ViewerMark) -> str:
    """The overlay's repeated line (plain text): name, organisation, EAT date and view id."""
    parts = [viewer.name, viewer.org_name or "owner preview", eat(viewer.viewed_at)]
    if viewer.view_id is not None:
        parts.append(f"view {viewer.view_id}")
    return " · ".join(parts)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _link(url: str) -> str:
    safe = urlsplit(url).scheme.lower() in ("http", "https")
    if not safe:
        return f"<li>{escape(url)}</li>"
    attributes = f'href="{escape(url, quote=True)}" rel="noopener noreferrer nofollow" target="_blank"'
    return f"<li><a {attributes}>{escape(url)}</a></li>"


def _meta(name: str, value: str) -> str:
    return f'<meta name="bridge:{name}" content="{escape(value, quote=True)}">'


def render_document(*, title: str, document: Mapping[str, Any], owner: OwnerMark, viewer: ViewerMark) -> str:
    """The HTML page of one Tier-2 document for one viewer."""
    metas = [
        _meta("viewer", viewer.name),
        _meta("viewer-org", viewer.org_name or ""),
        _meta("viewed-on", eat(viewer.viewed_at, seconds=True)),
        _meta("cert-id", owner.cert_id),
    ]
    if viewer.view_id is not None:
        metas.insert(0, _meta("view-id", str(viewer.view_id)))
    else:
        metas.insert(0, _meta("render", "owner-preview"))
    tile = f"<span>{escape(mark_text(viewer))}</span>"
    body = [
        f'<p class="label">{escape(CONFIDENTIAL)}</p>',
        f"<h1>{escape(title)}</h1>",
        (
            f'<p class="owner">By {escape(owner.name)} · Certificate {escape(owner.cert_id)} · Registered '
            f"{escape(eat(owner.registered_at, seconds=True))} · "
            # A new top-level tab: the web app frames this page in a sandbox, and /verify refuses to be framed.
            f'<a href="{escape(owner.verify_url, quote=True)}" rel="noopener noreferrer nofollow" target="_blank">'
            "Verify this record</a></p>"
        ),
    ]
    for key, label in SECTIONS:
        value = _text(document.get(key))
        if value is not None:
            body.append(f'<section><h2>{label}</h2><div class="text">{escape(value)}</div></section>')
    links = [link for link in document.get("links") or [] if _text(link)]
    if links:
        body.append(f"<section><h2>Links</h2><ul>{''.join(_link(link) for link in links)}</ul></section>")
    names = [_text(entry.get("file_name")) for entry in document.get("attachments") or [] if isinstance(entry, dict)]
    if any(names):
        items = "".join(f"<li>{escape(name)}</li>" for name in names if name)
        body.append(
            f'<section><h2>Attachments</h2><ul>{items}</ul><p class="note">{escape(ATTACHMENTS_NOTE)}</p></section>'
        )
    note = MARK_NOTE if viewer.view_id is not None else OWNER_NOTE
    body.append(f'<p class="mark">{escape(mark_text(viewer))}. {escape(note)}</p>')
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow, noarchive">'
        f"{''.join(metas)}<title>{escape(title)} · Confidential</title><style>{STYLE}</style></head><body>"
        f'<div class="overlay" aria-hidden="true">{tile * TILES}</div>'
        f"<main>{''.join(body)}</main></body></html>"
    )
