"""Schema v10 (P23-1): profile and problem embeddings for the ranker's f1 (REQ-PERS-01, REQ-PERS-02, REQ-EMB-01).

Design: ``docs/platform/tasks/P23.md`` section "P23-1 as built" (D-63 pending: ``app_peers`` is unchanged, the
embedding serves recommendations only). AC-PERS-3: a withdrawal of the ``profiling`` consent removes the profile's
vector in its own transaction and no vector is written while the consent is not granted. Additive but for one
narrowing of an earlier grant, restored on downgrade: two new columns (``developer_profiles.profile_embedded_at``,
``problems.embedded_at``), two HNSW cosine indexes, fourteen new functions (six granted to bridge_app, six internal,
two trigger functions) and two triggers. No new table, no enum type, no policy change; nothing else of revisions 0001
to 0011 is changed or dropped. The downgrade drops the triggers, functions, indexes and the two time columns and
restores the grant; the vectors themselves (revisions 0001 and 0002's columns) stay where they are. Every vector is
derived data the worker recomputes from rows that stay, so the downgrade loses nothing anyone wrote and proceeds with
rows: it nulls nothing and needs no ``-x`` flag (unlike 0010 and 0011's).

- ``developer_profiles`` (revision 0001; USER, own-row policies unchanged): ``profile_embedded_at`` (when
  ``app_set_profile_embedding`` wrote the vector, the database's clock; NULL while there is none), readable with the
  own row like every column (bridge_app's table-wide SELECT and INSERT of revision 0001 cover it, as they cover the
  vector; profiles are created by the signup with these columns NULL). bridge_app's UPDATE stays revision 0001's
  and 0011's columns (headline, bio, county_code, updated_at, peers_visible): never the vector, its model and version
  or its time. Index ``ix_developer_profiles_profile_embedding`` (HNSW, ``vector_cosine_ops``, pgvector's defaults
  like ``ix_proposals_teaser_embedding``).
- ``problems`` (revision 0002; PUBLISHED, policies unchanged): ``embedded_at`` likewise. The one narrowing: revisions
  0002 and 0005 left ``embedding``, ``embed_model`` and ``embed_version`` in bridge_app's column-scoped INSERT and
  UPDATE, which no code uses; with f1 a cosine against these vectors, a problem's author could plant the vector the
  ranker reads. This revision revokes both on the three columns (the card: "the column grants stay closed to
  bridge_app"); ``embedded_at`` is in neither (problems' INSERT and UPDATE are column-scoped). Index
  ``ix_problems_embedding`` (HNSW, ``vector_cosine_ops``).
- ``consents`` (revision 0001; append-only): ``consents_profiling_withdrawn`` (AFTER INSERT, every role, WHEN the row
  is ``profiling`` and not granted) nulls the profile's vector, model, version and time in the inserting transaction,
  under the profile's row lock, whatever the app does next. The app also calls ``app_clear_profile_embedding`` in the
  opt-out request (belt and braces; the second call finds nothing to clear).
- ``developer_niches`` (revision 0001): ``developer_niches_liked_changed`` (AFTER INSERT OR UPDATE OR DELETE, every
  role) moves the profile's ``updated_at`` to ``now()`` when a liked niche is added, removed or changed (a weight
  change, or a followed niche, changes nothing). ``developer_niches`` has no time of its own, so this is how a
  liked-niche change makes the profile's vector stale (``updated_at`` later than ``profile_embedded_at``).

Staleness compares ``now()``-stamped times: ``updated_at`` (the ORM's ``onupdate``, the moderation definers),
``proposals.published_at``, ``hidden_at`` and ``updated_at`` (the publish and lifecycle SQL) are all transaction
times, so ``profile_embedded_at`` and ``embedded_at`` are ``now()`` too, never ``app_clock_now()``: a moved test clock
(the demo's) would otherwise make every later change look older than the vector.

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``; each refuses with a message naming itself; "the worker" is bridge_app with no user bound,
as revisions 0007 to 0011's jobs; a model or version label is 1 to 80 or 1 to 40 characters, not blank, without a
control character; a vector has exactly 1,024 dimensions and is not the zero vector (cosine is undefined there; NaN
and infinities are pgvector's refusals); invalid_parameter_value otherwise, and for a limit outside 1 to 1,000):

- ``app_profiles_to_embed(model, version, limit)`` -> (user_id, text): the worker only (insufficient_privilege for a
  bound session). Developers (a profile; the user active and not staff) whose latest ``profiling`` consent (by
  ``created_at``, then ``id``: ``bridge.profiles.consents.latest``'s order) is granted and whose vector is stale: none,
  no ``profile_embedded_at``, another model or version, ``updated_at`` later than ``profile_embedded_at`` (a profile
  edit or a liked-niche change), or one of their proposals published, hidden, or (while published) changed later than
  it. ``text``: the headline, the bio, the liked niches' English names (by ``sort_order``, name, id, as
  ``bridge.profiles.niches.liked``), then the title and problem statement of their five latest published proposals
  (``status = 'published'``, newest ``published_at`` first; Tier-1 teaser columns only), each NFKC-normalised with
  every run of whitespace or control characters collapsed to one space and trimmed, empty parts left out, joined by
  newlines and cut at 8,000 characters. A developer with nothing to embed (an empty text) is not listed. Oldest
  ``profile_embedded_at`` first (never embedded first), then user id. Never a developer whose consent is not granted.
- ``app_set_profile_embedding(user, vector, model, version)`` -> boolean: the worker only. Locks the profile FOR
  UPDATE first and then reads the consent afresh (a withdrawal in flight holds the same row lock through its trigger,
  so it is waited for and its outcome read): writes the vector, model, version and ``profile_embedded_at = now()``
  and returns true only while the latest ``profiling`` consent is granted and the user is active and not staff;
  false, writing nothing, otherwise (and for a user without a profile).
- ``app_clear_profile_embedding(user)``: nulls the vector, model, version and time (under the row lock). The worker
  for any user, or a bound user for their own row only (the opt-out runs in the user's request); insufficient_privilege
  for anyone else. An unknown user or an empty row is a no-op.
- ``app_problems_to_embed(model, version, limit)`` -> (problem_id, text): the worker only. Published and clear problems
  whose vector is stale (none, no ``embedded_at``, another model or version, ``updated_at`` later than
  ``embedded_at``); ``text`` the title and statement, normalised as above; oldest ``embedded_at`` first (never
  embedded first), then id.
- ``app_set_problem_embedding(problem, vector, model, version)`` -> boolean: the worker only. Locks the problem FOR
  UPDATE and writes the vector, model, version and ``embedded_at = now()`` only while it is published and clear (a
  hold or archive since it was listed: false, nothing written).
- ``app_stale_embedding_counts(model DEFAULT NULL, version DEFAULT NULL)`` -> one row (profiles, problems): the worker
  only; how many rows the two readers would list (for the job's log line). Without a model and version (both or
  neither) the model rule is left out: rows without a vector or changed since they were embedded.
- Internal (no EXECUTE grant; called as the owner): ``embedding_label_is_valid(label, max)``,
  ``embedding_text_line(text)``, ``profile_consent_granted(user)``, ``profile_embedding_text(user)``,
  ``profiles_to_embed(model, version)`` and ``problems_to_embed(model, version)`` (the stale sets with their times and
  texts, unordered; NULL model and version leave the model rule out), ``profile_embedding_clear(user)``.

Lock order: a profile's row lock, then the consent read (the writer; a withdrawal's trigger takes the same row lock);
a problem's row lock, then its state (the writer; a moderation decision updates the same row).

Operating rules for the code that uses this schema:

- The job (``embeddings.reembed``, unbound): ``SELECT user_id, text FROM app_profiles_to_embed(:model, :version,
  :limit)``, embed, then ``SELECT app_set_profile_embedding(:user, CAST(:vector AS vector), :model, :version)`` per
  row (false: the consent was withdrawn or the account changed meanwhile; skip it, it will not be listed again). The
  same for problems with ``app_problems_to_embed`` and ``app_set_problem_embedding``. Log
  ``app_stale_embedding_counts(:model, :version)`` after the run. A row edited between its listing and its write is
  stamped as embedded with the older text (timestamps, not a content hash): it is picked up at its next change or the
  next model or version. ``reembed``'s stall check sees a row edited after its write in the same run as stale again:
  give each run a bound, or skip rows already written in the run, rather than failing.
- The opt-out (PUT /consents with ``profiling`` false, bound to the user): record the decision as today (the trigger
  clears the vector in that transaction) and call ``app_clear_profile_embedding(:me)`` in the same transaction.
- The ranker: use a vector only when it is not NULL, ``embedded_at`` / ``profile_embedded_at`` is set and the model
  and version are the embedder's, and only for a developer whose ``profiling`` consent is granted (as today's f1 and
  f9). Never read ``developer_profiles.profile_embedding`` of another user (own-row RLS); a problem's vector is read
  with the problem.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_developer_profiles_profile_embedding", "developer_profiles", "profile_embedding"),
    ("ix_problems_embedding", "problems", "embedding"),
)


def upgrade() -> None:
    op.add_column("developer_profiles", sa.Column("profile_embedded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("problems", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
    for name, table, column in INDEXES:
        op.create_index(
            name, table, [column], unique=False, postgresql_using="hnsw", postgresql_ops={column: "vector_cosine_ops"}
        )


def downgrade() -> None:
    """Not destructive: the two times and the indexes are derived data; the vectors stay."""
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_column("problems", "embedded_at")
    op.drop_column("developer_profiles", "profile_embedded_at")
