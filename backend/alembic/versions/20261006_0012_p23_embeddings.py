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

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0011: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; internal and trigger functions to nobody).
# SECURITY DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- A model or version label: 1 to p_max characters, not blank, without a control character. Internal (no EXECUTE
-- grant): the definers below.
CREATE FUNCTION embedding_label_is_valid(p_label text, p_max integer) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT coalesce(p_label ~ '[^[:space:]]' AND char_length(p_label) <= p_max AND p_label !~ '[[:cntrl:]]', false)
$$;

-- One part of an embedding's text: NFKC-normalised, every run of whitespace or control characters one space, trimmed;
-- NULL when nothing is left. Internal (no EXECUTE grant).
CREATE FUNCTION embedding_text_line(p_text text) RETURNS text
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT nullif(btrim(regexp_replace(normalize(p_text, NFKC), '[[:space:][:cntrl:]]+', ' ', 'g')), '')
$$;

-- Whether p_user's latest profiling decision (bridge.profiles.consents.latest's order: created_at, then id) is a
-- grant; no decision is no consent. Internal (no EXECUTE grant).
CREATE FUNCTION profile_consent_granted(p_user uuid) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT coalesce((SELECT c.granted FROM public.consents c
                      WHERE c.user_id = p_user AND c.purpose = 'profiling'
                      ORDER BY c.created_at DESC, c.id DESC LIMIT 1), false)
$$;

-- The text p_user's profile vector is computed from: the headline, the bio, the liked niches' English names (in
-- bridge.profiles.niches.liked's order), then the title and problem statement of the five latest published proposals
-- (newest first; Tier-1 teaser columns only), each one embedding_text_line, empty parts left out, joined by newlines
-- and cut at 8,000 characters; '' when there is nothing. Internal (no EXECUTE grant).
CREATE FUNCTION profile_embedding_text(p_user uuid) RETURNS text
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT left(array_to_string(ARRAY(
        SELECT public.embedding_text_line(part.body)
          FROM (SELECT 1 AS kind, 0::bigint AS n, 0 AS k, d.headline::text AS body
                  FROM public.developer_profiles d WHERE d.user_id = p_user
                UNION ALL
                SELECT 2, 0, 0, d.bio FROM public.developer_profiles d WHERE d.user_id = p_user
                UNION ALL
                SELECT 3, row_number() OVER (ORDER BY n.sort_order, n.name_en, n.id), 0, n.name_en::text
                  FROM public.developer_niches l JOIN public.niches n ON n.id = l.niche_id
                 WHERE l.user_id = p_user AND l.kind = 'liked'
                UNION ALL
                SELECT 4, q.n, v.k, v.body
                  FROM (SELECT p.title, p.problem_statement,
                               row_number() OVER (ORDER BY p.published_at DESC NULLS LAST, p.id DESC) AS n
                          FROM public.proposals p
                         WHERE p.owner_id = p_user AND p.status = 'published'
                         ORDER BY p.published_at DESC NULLS LAST, p.id DESC
                         LIMIT 5) q
                 CROSS JOIN LATERAL (VALUES (1, q.title::text), (2, q.problem_statement)) AS v(k, body)) part
         ORDER BY part.kind, part.n, part.k), E'\n'), 8000)
$$;

-- The developers whose profile vector is stale, with their vector's time and text: a profile whose user is active and
-- not staff, whose latest profiling decision is a grant, with no vector, no time, another model or version (left out
-- when p_model is NULL), an edit or a liked-niche change since (updated_at), or a proposal of theirs published, hidden
-- or (while published) changed since; and a text that is not empty. Unordered. Internal (no EXECUTE grant).
CREATE FUNCTION profiles_to_embed(p_model text, p_version text)
    RETURNS TABLE (user_id uuid, embedded_at timestamptz, body text)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    WITH stale AS MATERIALIZED (
        SELECT d.user_id, d.profile_embedded_at
          FROM public.developer_profiles d
          JOIN public.users u ON u.id = d.user_id
         WHERE u.status = 'active' AND u.staff_role IS NULL
           AND public.profile_consent_granted(d.user_id)
           AND (d.profile_embedding IS NULL OR d.profile_embedded_at IS NULL
                OR (p_model IS NOT NULL
                    AND (d.embed_model IS DISTINCT FROM p_model OR d.embed_version IS DISTINCT FROM p_version))
                OR d.updated_at > d.profile_embedded_at
                OR EXISTS (SELECT 1 FROM public.proposals p
                            WHERE p.owner_id = d.user_id
                              AND (p.published_at > d.profile_embedded_at OR p.hidden_at > d.profile_embedded_at
                                   OR (p.status = 'published' AND p.updated_at > d.profile_embedded_at))))
    )
    SELECT s.user_id, s.profile_embedded_at, t.body
      FROM stale s CROSS JOIN LATERAL (SELECT public.profile_embedding_text(s.user_id) AS body) t
     WHERE t.body <> ''
$$;

-- The published and clear problems whose vector is stale (no vector, no time, another model or version (left out when
-- p_model is NULL), or an edit since), with the vector's time and the text: title and statement, each
-- embedding_text_line, joined by a newline and cut at 8,000 characters (an empty text is left out). Unordered.
-- Internal (no EXECUTE grant).
CREATE FUNCTION problems_to_embed(p_model text, p_version text)
    RETURNS TABLE (problem_id uuid, embedded_at timestamptz, body text)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT s.id, s.embedded_at, s.body
      FROM (SELECT p.id, p.embedded_at,
                   left(array_to_string(ARRAY[public.embedding_text_line(p.title),
                                              public.embedding_text_line(p.statement)], E'\n'), 8000) AS body
              FROM public.problems p
             WHERE p.status = 'published' AND p.moderation_state = 'clear'
               AND (p.embedding IS NULL OR p.embedded_at IS NULL
                    OR (p_model IS NOT NULL
                        AND (p.embed_model IS DISTINCT FROM p_model OR p.embed_version IS DISTINCT FROM p_version))
                    OR p.updated_at > p.embedded_at)) s
     WHERE s.body <> ''
$$;

-- Nulls p_user's profile vector, model, version and time, under the profile's row lock (taken even when there is
-- nothing to clear, so a writer in flight is waited for, or waits). Internal (no EXECUTE grant): the clearer and the
-- consents trigger, as the owner.
CREATE FUNCTION profile_embedding_clear(p_user uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    PERFORM 1 FROM public.developer_profiles d WHERE d.user_id = p_user FOR UPDATE;
    UPDATE public.developer_profiles d
       SET profile_embedding = NULL, embed_model = NULL, embed_version = NULL, profile_embedded_at = NULL
     WHERE d.user_id = p_user
       AND (d.profile_embedding IS NOT NULL OR d.embed_model IS NOT NULL OR d.embed_version IS NOT NULL
            OR d.profile_embedded_at IS NOT NULL);
END;
$$;

-- A page of the developers whose profile vector the worker computes next (REQ-PERS-02; AC-PERS-3: only while the
-- profiling consent is granted): profiles_to_embed's set, never embedded first, then the oldest vector, then user id.
-- The worker only (no user bound): a signed-in session learns nothing of other developers' profiles.
CREATE FUNCTION app_profiles_to_embed(p_model text, p_version text, p_limit integer)
    RETURNS TABLE (user_id uuid, text text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_profiles_to_embed: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40))
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'app_profiles_to_embed: a model (1 to 80 characters), a version (1 to 40) and a limit of 1 to'
            ' 1000' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT s.user_id, s.body
      FROM public.profiles_to_embed(p_model, p_version) s
     ORDER BY s.embedded_at ASC NULLS FIRST, s.user_id
     LIMIT p_limit;
END;
$$;

-- Writes p_user's profile vector (REQ-PERS-02; AC-PERS-3): the worker only. The profile's row is locked first, then the
-- consent read afresh, so a withdrawal in flight (its trigger locks the same row) is waited for and its outcome read;
-- written with the model, version and now() only while the latest profiling decision is a grant and the user is active
-- and not staff. Returns whether it wrote.
CREATE FUNCTION app_set_profile_embedding(p_user uuid, p_vector vector, p_model text, p_version text)
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_set_profile_embedding: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_vector IS NULL OR vector_dims(p_vector) <> 1024 OR vector_norm(p_vector) = 0
       OR NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40)) THEN
        RAISE EXCEPTION 'app_set_profile_embedding: a non-zero vector of 1024 dimensions, a model (1 to 80 characters)'
            ' and a version (1 to 40)' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM 1 FROM public.developer_profiles d WHERE d.user_id = p_user FOR UPDATE;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    IF NOT public.profile_consent_granted(p_user)
       OR NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_user AND u.status = 'active' AND u.staff_role IS NULL)
    THEN
        RETURN false;
    END IF;
    UPDATE public.developer_profiles d
       SET profile_embedding = p_vector, embed_model = p_model, embed_version = p_version, profile_embedded_at = now()
     WHERE d.user_id = p_user;
    RETURN true;
END;
$$;

-- Clears p_user's profile vector (REQ-PERS-02; AC-PERS-3, the opt-out): the worker for anyone, or a signed-in user for
-- their own profile only (the opt-out runs in their request); anyone else is refused.
CREATE FUNCTION app_clear_profile_embedding(p_user uuid) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL AND p_user IS DISTINCT FROM public.app_user_id() THEN
        RAISE EXCEPTION 'app_clear_profile_embedding: the caller''s own profile, or the embedding worker with no user'
            ' bound' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM public.profile_embedding_clear(p_user);
END;
$$;

-- A page of the problems whose vector the worker computes next (REQ-EMB-01): problems_to_embed's set, never embedded
-- first, then the oldest vector, then id. The worker only (no user bound).
CREATE FUNCTION app_problems_to_embed(p_model text, p_version text, p_limit integer)
    RETURNS TABLE (problem_id uuid, text text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_problems_to_embed: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40))
       OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'app_problems_to_embed: a model (1 to 80 characters), a version (1 to 40) and a limit of 1 to'
            ' 1000' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT s.problem_id, s.body
      FROM public.problems_to_embed(p_model, p_version) s
     ORDER BY s.embedded_at ASC NULLS FIRST, s.problem_id
     LIMIT p_limit;
END;
$$;

-- Writes p_problem's vector (REQ-EMB-01): the worker only. The problem's row is locked, then its state read: written
-- with the model, version and now() only while it is published and clear (a hold or an archive since it was listed
-- writes nothing). Returns whether it wrote.
CREATE FUNCTION app_set_problem_embedding(p_problem uuid, p_vector vector, p_model text, p_version text)
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status public.problem_status;
    v_state public.moderation_state;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_set_problem_embedding: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_vector IS NULL OR vector_dims(p_vector) <> 1024 OR vector_norm(p_vector) = 0
       OR NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40)) THEN
        RAISE EXCEPTION 'app_set_problem_embedding: a non-zero vector of 1024 dimensions, a model (1 to 80 characters)'
            ' and a version (1 to 40)' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT p.status, p.moderation_state INTO v_status, v_state FROM public.problems p WHERE p.id = p_problem FOR UPDATE;
    IF NOT FOUND OR v_status <> 'published' OR v_state <> 'clear' THEN
        RETURN false;
    END IF;
    UPDATE public.problems p
       SET embedding = p_vector, embed_model = p_model, embed_version = p_version, embedded_at = now()
     WHERE p.id = p_problem;
    RETURN true;
END;
$$;

-- How many rows the two readers would list (the embedding job's log line): the worker only. With a model and version
-- (both or neither) the model rule applies; without, rows with no vector or changed since they were embedded.
CREATE FUNCTION app_stale_embedding_counts(p_model text DEFAULT NULL, p_version text DEFAULT NULL)
    RETURNS TABLE (profiles bigint, problems bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_stale_embedding_counts: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT ((p_model IS NULL AND p_version IS NULL)
            OR (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40))) THEN
        RAISE EXCEPTION 'app_stale_embedding_counts: a model (1 to 80 characters) and a version (1 to 40), or neither'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT (SELECT count(*) FROM public.profiles_to_embed(p_model, p_version)),
           (SELECT count(*) FROM public.problems_to_embed(p_model, p_version));
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_profiles_to_embed(text, text, integer)": ("bridge_app",),  # the worker, no user bound
    "app_set_profile_embedding(uuid, vector, text, text)": ("bridge_app",),  # the worker, no user bound
    "app_clear_profile_embedding(uuid)": ("bridge_app",),  # the worker, or the user's own opt-out
    "app_problems_to_embed(text, text, integer)": ("bridge_app",),  # the worker, no user bound
    "app_set_problem_embedding(uuid, vector, text, text)": ("bridge_app",),  # the worker, no user bound
    "app_stale_embedding_counts(text, text)": ("bridge_app",),  # the worker's log line, no user bound
}
INTERNAL_FUNCTIONS = (
    "profile_embedding_clear(uuid)",
    "profiles_to_embed(text, text)",
    "problems_to_embed(text, text)",
    "profile_embedding_text(uuid)",
    "profile_consent_granted(uuid)",
    "embedding_text_line(text)",
    "embedding_label_is_valid(text, integer)",
)
TRIGGER_FUNCTIONS: tuple[str, ...] = ()


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants: list[str] = []
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    op.add_column("developer_profiles", sa.Column("profile_embedded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("problems", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))
    for name, table, column in INDEXES:
        op.create_index(
            name, table, [column], unique=False, postgresql_using="hnsw", postgresql_ops={column: "vector_cosine_ops"}
        )
    _run_sql(FUNCTIONS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Not destructive: the vectors (revisions 0001 and 0002's columns) stay, and what goes (the two times, the indexes,
    the functions and triggers) is derived data and code. The worker recomputes every vector from rows that stay, so
    the downgrade proceeds with rows and nulls nothing. bridge_app's INSERT and UPDATE of problems' embedding columns
    (revisions 0002 and 0005) are granted again."""
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_column("problems", "embedded_at")
    op.drop_column("developer_profiles", "profile_embedded_at")
