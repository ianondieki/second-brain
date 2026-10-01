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
Content-Security-Policy allows only the one stylesheet below (by hash). Responses are never cached (``HEADERS``).
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
    # The P18 palette (frontend/app/globals.css) in a page that loads nothing: no web fonts (a serif stack for the
    # title), no images (the lattice echo is a gradient band). The per-viewer mark keeps its ink, opacity and size from
    # before the restyle (spec 06 §6.4 item 3: it must survive a screenshot's compression).
    ":root{color-scheme:light}"
    'body{margin:0;background:#fbfaf6;color:#1a1916;font:16px/1.6 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",'
    "Roboto,sans-serif}"
    "body::before{content:'';display:block;height:6px;background:repeating-linear-gradient(-45deg,#1f5e49 0 5px,"
    "#b89a4a 5px 10px)}"
    "main{position:relative;max-width:46rem;margin:0 auto;padding:2rem 1.25rem 4rem}"
    ".label{margin:0;color:#7a5a12;font-size:.75rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase}"
    'h1{margin:.35rem 0 .5rem;font:500 1.75rem/1.2 Newsreader,"Iowan Old Style",Georgia,"Times New Roman",serif;'
    "letter-spacing:-.01em}"
    'h2{margin:2rem 0 .5rem;font:500 1.2rem/1.3 Newsreader,"Iowan Old Style",Georgia,"Times New Roman",serif}'
    ".owner,.note,.mark{color:#5c5a53;font-size:.9rem}"
    ".text{white-space:pre-wrap;overflow-wrap:anywhere}"
    "a{color:#1f5e49;text-decoration-thickness:1px;text-underline-offset:.2em;overflow-wrap:anywhere}"
    "ul{padding-left:1.25rem}"
    ".mark{margin-top:3rem;padding-top:1rem;border-top:1px solid #dedacf}"
    ".overlay{position:fixed;inset:-50%;z-index:2;display:grid;"
    "grid-template-columns:repeat(auto-fill,minmax(18rem,1fr));gap:4rem 2.5rem;padding:2rem;"
    "transform:rotate(-24deg);pointer-events:none;user-select:none;opacity:.14;color:#1a1916;font-size:.8rem;"
    "font-weight:500;letter-spacing:.03em;line-height:1.3;overflow-wrap:anywhere}"
    "@media print{.overlay{opacity:.2}}"
)
STYLE_HASH: Final = base64.b64encode(hashlib.sha256(STYLE.encode("utf-8")).digest()).decode("ascii")
HEADERS: Final = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Content-Security-Policy": (
        f"default-src 'none'; style-src 'sha256-{STYLE_HASH}'; base-uri 'none'; form-action 'none';"
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
    return ts.astimezone(NAIROBI).strftime("%Y-%m-%d %H:%M:%S EAT" if seconds else "%Y-%m-%d %H:%M EAT")


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
