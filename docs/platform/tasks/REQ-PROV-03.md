# REQ-PROV-03

- Task: T2.5 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend; security-reviewer (Fable)
- Files owned: `bridge/proposals/render.py`, `bridge/proposals/views.py`
- Depends on: T2.3, T2.4.

## Scope

Per-viewer marks on Tier-2/3 renders (visible tiled overlay with viewer name, org, `view_id` and EAT date; `view_id` in HTML meta and PDF metadata) and the access log (`document_views`). The trace tool is Phase 3 (T3.10, AC-IP-3/a).

## Acceptance criteria and tests

AC-REPO-2 (`integration/proposals/test_render_marks.py`).

## Prototype P3 (T2.5 minimal, 2026-09-29): built

- `bridge/proposals/render.py`: the server-side HTML render (Release 1 marks). Owner attribution: the version's
  `owner_handle` until the organisation's engagement reaches `INTEREST_CONFIRMED` or a later main-path stage
  (`access.REVEALED_STATES`), the owner's display name after; certificate id, `registered_at` in EAT and the
  `/verify/{cert_id}` link. Per-viewer mark: 120 tiles of "name · organisation · YYYY-MM-DD HH:MM EAT · view
  {view_id}" in a fixed, rotated overlay (`aria-hidden`, no pointer events, printed too), the same values in
  `<meta name="bridge:view-id|viewer|viewer-org|viewed-on|cert-id">`, and a plain-text line at the end with the honest
  note that the mark traces a leak and cannot stop a screenshot (`[[COPY-REVIEW]]`). Every value is HTML-escaped; only
  http(s) links become anchors; attachment file names only (never object keys). Headers: `Cache-Control: no-store,
  no-cache, must-revalidate, private, max-age=0`, `Pragma: no-cache`, `Expires: 0`, CSP `default-src 'none'` with the
  one stylesheet by hash (no script), `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN` (the web app may
  frame it through its same-origin `/api` rewrite), `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`.
- `bridge/proposals/views.py`: `render` reads Tier 2 as `tier2_reader`, writes the `document_views` row (id = the
  page's `view_id`, `render_kind` html, the viewer's NDA acceptance and its template version, a 16-byte
  `fingerprint_seed` for the Release 2 marks; `started_at` is the database's and is the date printed) and a
  `tier2.viewed` audit event (ids, the render kind and the NDA version) on the organisation's chain, and commits before
  the page is served. The owner's preview is audited as `proposal.tier2_read` (`render: html`) and never logged as a
  view. `who_has_seen` backs `GET /api/me/proposals/{id}/views` (owner only, 404 otherwise; newest first, at most 500:
  view id, time, organisation id and name, viewer name, version, render kind, duration bucket, NDA version).
- Tests: `integration/proposals/test_render_marks.py` (AC-REPO-2), `unit/proposals/test_render.py`.

## After prototype (rescheduled, not removed)

- The PDF render with `view_id` in the PDF metadata, attachment renders and raw download (docs/spec/06 6.1).
- Coarse view durations: `duration_bucket` stays NULL until a client heartbeat reports them.
- The trace tool (T3.10, AC-IP-3/a): it can read `bridge:view-id` and the overlay's `view {id}` today.
- A QR code next to the `/verify` link (the certificate PDF has one).

