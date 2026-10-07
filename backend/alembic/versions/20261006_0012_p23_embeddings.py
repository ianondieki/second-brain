"""Schema v10 (P23-1): profile and problem embeddings for the ranker's f1 (REQ-PERS-01, REQ-PERS-02, REQ-EMB-01).

Design: ``docs/platform/tasks/P23.md`` section "P23-1 as built" (D-63 pending: ``app_peers`` is unchanged, the
embedding serves recommendations only). AC-PERS-3: a withdrawal of the ``profiling`` consent removes the profile's
vector in its own transaction and no vector is written while the consent is not granted. Additive but for two
narrowings of earlier objects, restored on downgrade (a grant on ``problems``, the INSERT policy of
``developer_profiles``): four new columns (``developer_profiles.profile_embedded_at`` and
``profile_embedding_hash``, ``problems.embedded_at`` and ``embedding_hash``), two HNSW cosine indexes, twenty-four new
functions (seven granted to bridge_app, fifteen internal, two trigger functions) and two triggers. No new table, no enum
type; nothing else of revisions 0001 to 0011 is changed or dropped. The downgrade nulls every vector with its model
and version on both tables, then drops the triggers, functions, indexes and the four new columns and restores the grant
and the policy. Every vector is derived data the worker recomputes from rows that stay (the profiles, niches,
proposals and problems), and without its hash nothing would say which text a vector came from, so the downgrade
clears them rather than keep vectors 0011 cannot judge; it loses nothing anyone wrote and proceeds with rows, needing
no ``-x`` flag (unlike 0010 and 0011's). After a re-upgrade every consented profile and published problem is listed
again.

Freshness is content-based: a vector is stored with the SHA-256 (hex) of the exact text it was computed from
(``profile_embedding_hash``, ``embedding_hash``), and a row is stale when it has no vector, another model or version,
or a stored hash that is not the hash of the text as it reads now. So any change to what the text is made of (a
profile edit, a liked niche added, removed or renamed, a proposal published, hidden or with a new teaser, a problem
edited) makes the row stale, and nothing else does (an ``updated_at`` moved by an unrelated update, a followed niche, a
weight, a draft). A writer recomputes the text under the row lock and refuses a hash that is no longer the text's, so
an edit that commits between the listing and the write is never stamped as embedded.

- ``developer_profiles`` (revision 0001; USER, own-row policies): ``profile_embedded_at`` (when
  ``app_set_profile_embedding`` wrote the vector, the database's ``now()``; NULL while there is none; the readers'
  order) and ``profile_embedding_hash``, readable with the own row like every column (bridge_app's table-wide SELECT
  of revision 0001). Revision 0001's table-wide INSERT covers them too, so the INSERT policy ``bridge_app_insert``
  gains that a profile is inserted without an embedding: the vector, model, version, time and hash NULL (the signup's
  ORM insert sends NULLs), so no vector or hash is ever planted at creation. bridge_app's UPDATE stays revision
  0001's and 0011's columns (headline, bio, county_code, updated_at, peers_visible): never the vector, its model,
  version, time or hash. Index ``ix_developer_profiles_profile_embedding`` (HNSW, ``vector_cosine_ops``, pgvector's
  defaults like ``ix_proposals_teaser_embedding``).
- ``problems`` (revision 0002; PUBLISHED, policies unchanged): ``embedded_at`` and ``embedding_hash`` likewise. The
  grant narrowing: revisions 0002 and 0005 left ``embedding``, ``embed_model`` and ``embed_version`` in bridge_app's
  column-scoped INSERT and UPDATE, which no code uses; with f1 a cosine against these vectors, a problem's author could
  plant the vector the ranker reads. This revision revokes both on the three columns (the card: "the column grants
  stay closed to bridge_app"); the two new columns are in neither (problems' INSERT and UPDATE are column-scoped).
  Index ``ix_problems_embedding`` (HNSW, ``vector_cosine_ops``).
- ``consents`` (revision 0001; append-only): ``consents_profiling_withdrawn`` (AFTER INSERT, every role, WHEN the row
  is ``profiling`` and not granted) nulls the profile's vector, model, version, time and hash in the inserting
  transaction and moves ``updated_at`` to ``now()``, always writing the row (even without a vector), whatever the app
  does next. The app also calls ``app_clear_profile_embedding`` in the opt-out request (belt and braces; the second
  call finds nothing to clear). ``consents_created_now`` (BEFORE INSERT, SECURITY INVOKER) sets ``created_at`` to
  ``now()`` for every writer but the table's owner (a seed or a backfill keeps its own time): bridge_app's INSERT is
  table-wide, and ``created_at`` decides which decision is the latest, so a future-dated grant followed by a
  withdrawal would otherwise leave the grant "latest" and the profile embeddable again. The latest decision is then
  the last inserted (then the highest id within one transaction, as ``bridge.profiles.consents.latest`` orders).
- ``developer_niches`` (revision 0001): no trigger. The text holds the liked niches' names, so the hash sees a liked
  niche added, removed or renamed without one.

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``; each refuses with a message naming itself; "the worker" is bridge_app with no user bound,
as revisions 0007 to 0011's jobs; a model or version label is 1 to 80 or 1 to 40 characters, not blank, without a
control character; a text hash is 64 lower-case hex digits; a vector has exactly 1,024 dimensions and is not the zero
vector (cosine is undefined there; NaN and infinities are pgvector's refusals); invalid_parameter_value otherwise, and
for a limit outside 1 to 1,000; the two writers run at READ COMMITTED only, invalid_transaction_state otherwise, as
revision 0001's audit trigger):

- ``app_profiles_to_embed(model, version, limit)`` -> (user_id, text, text_hash): the worker only
  (insufficient_privilege for a bound session). Developers (a profile; the user active and not staff) whose latest
  ``profiling`` consent (by ``created_at``, then ``id``: ``bridge.profiles.consents.latest``'s order) is granted and
  whose vector is stale: none, another model or version, or a stored hash that is not ``text_hash``. ``text``: the
  headline, the bio, the liked niches' English names (by ``sort_order``, name, id, as ``bridge.profiles.niches.liked``),
  then the title and problem statement of their five latest published proposals (``status = 'published'``, newest
  ``published_at`` first; Tier-1 teaser columns only), each NFKC-normalised with every run of whitespace or control
  characters collapsed to one space and trimmed, empty parts left out, joined by newlines and cut at 8,000 characters;
  ``text_hash`` its SHA-256 (UTF-8, hex). A developer with nothing to embed (an empty text) is not listed. Two
  stages: the developers without a vector first (never embedded first, then the oldest ``profile_embedded_at``, then
  user id), then, only while the page is not full, those with a vector whose model or version differs or whose text
  changed (oldest ``profile_embedded_at`` first, then user id); a text is built only for the developers looked at.
  Never a developer whose consent is not granted.
- ``app_set_profile_embedding(user, vector, model, version, text_hash)`` -> boolean: the worker only. Locks the profile
  FOR UPDATE first and then reads the consent and the text afresh (a withdrawal in flight holds the same row lock
  through its trigger, so it is waited for and its outcome read): writes the vector, model, version,
  ``profile_embedded_at = now()`` and the hash, and returns true, only while the latest ``profiling`` consent is
  granted, the user is active and not staff, and ``text_hash`` is the hash of the text as it reads now; false, writing
  nothing, otherwise (and for a user without a profile or with an empty text).
- ``app_clear_profile_embedding(user)``: nulls the vector, model, version, time and hash and moves ``updated_at`` (the
  row is always written, so it is locked). The worker for any user, or a bound user for their own row only (the
  opt-out runs in the user's request); insufficient_privilege for anyone else. An unknown user is a no-op.
- ``app_problems_to_embed(model, version, limit)`` -> (problem_id, text, text_hash): the worker only. Problems every
  signed-in developer may read (``problem_is_readable``: published and clear; an organisation's only while it is
  listed; a Brief's only while the Brief is published), whose vector is stale (none, another model or version, or a
  stored hash that is not ``text_hash``); ``text`` the title and statement, normalised as above; the same two
  stages by ``embedded_at``, then id.
- ``app_set_problem_embedding(problem, vector, model, version, text_hash)`` -> boolean: the worker only. Locks the
  problem FOR UPDATE and writes the vector, model, version, ``embedded_at = now()`` and the hash only while it is
  readable and ``text_hash`` is its text's hash now (a hold, an archive, a Brief back in draft, a delisting or an edit
  since it was listed: false, nothing written).
- ``app_clear_empty_embeddings()`` -> one row (profiles, problems): the worker only, at READ COMMITTED only; clears
  (vector, model, version, time and hash) every profile and problem holding a vector whose text is now empty (all it
  was computed from removed: never listed, since an empty text is not embedded), each under its row lock with its text
  read again, and says how many. One text build per row holding a vector.
- ``app_stale_embedding_counts(model DEFAULT NULL, version DEFAULT NULL)`` -> one row (profiles, problems): the worker
  only; how many rows the two readers would list plus how many ``app_clear_empty_embeddings`` would clear (for the
  job's log line). Without a model and version (both or
  neither) the model rule is left out: rows without a vector or whose text changed since.
- Internal (no EXECUTE grant; called as the owner): ``embedding_label_is_valid(label, max)``,
  ``embedding_text_line(text)``, ``embedding_text_hash(text)``, ``profile_consent_granted(user)``,
  ``profile_embedding_text(user)``, ``problem_embedding_text(title, statement)``, ``problem_is_readable(problem)``,
  ``embedding_is_stale(...)`` (the one staleness rule), ``profile_embedding_candidates()`` and
  ``problem_embedding_candidates()`` (who may be embedded, without a text built), ``profiles_to_embed(model,
  version)`` and ``problems_to_embed(model, version)`` (the stale sets, for the counts; NULL model and version leave
  the model rule out), ``empty_embedded_profiles()`` and ``empty_embedded_problems()`` (vectors whose text is empty
  now), ``profile_embedding_clear(user)``.

Lock order: a profile's row lock, then the consent and text reads (the writer; a withdrawal's trigger writes the same
row, so either waits for the other: at READ COMMITTED the writer then reads the withdrawal, and the withdrawal clears
what the writer left); a problem's row lock, then its state and text (the writer; a moderation decision or an edit
updates the same row). A change to a profile's niches or proposals takes no profile lock: committed before the
writer's read, the writer sees it (and refuses a stale hash); committed after, the stored hash is the older text's and
the row is listed again.

Operating rules for the code that uses this schema:

- The job (``embeddings.reembed``, unbound) starts each run with ``SELECT * FROM app_clear_empty_embeddings()``
  (its own transaction, READ COMMITTED), then ``SELECT user_id, text, text_hash FROM app_profiles_to_embed(:model,
  :version, :limit)``, embed ``text``, then ``SELECT app_set_profile_embedding(:user, CAST(:vector AS vector), :model,
  :version, :text_hash)`` per row with the hash the reader gave. False: the consent was withdrawn, the account changed
  or the text changed meanwhile; do not count the row as done (a changed text is listed again with its new hash, a
  withdrawn consent is not). The same for problems with ``app_problems_to_embed`` and ``app_set_problem_embedding``.
  Log ``app_stale_embedding_counts(:model, :version)`` after the run. Cost: a page of the first stage (rows without a
  vector) builds only its own rows' texts (and those of rows skipped for an empty text), so a backfill costs about
  one text build per row; the second stage (rows with a vector, reached only when the first leaves the page short)
  builds one text per embedded row it looks at, so a call that finds nothing stale costs one text build per embedded
  row; the counts build one text per candidate.
- The opt-out (PUT /consents with ``profiling`` false, bound to the user): record the decision as today (the trigger
  clears the vector in that transaction) and call ``app_clear_profile_embedding(:me)`` in the same transaction.
- The ranker: use a vector only when it is not NULL, its hash is set and the model and version are the embedder's, and
  only for a developer whose ``profiling`` consent is granted (as today's f1 and f9). Never read
  ``developer_profiles.profile_embedding`` of another user (own-row RLS); a problem's vector is read with the problem.

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

# Revisions 0002 (UPDATE) and 0005 (INSERT): bridge_app's column grants on problems' embedding columns, revoked here and
# granted again on downgrade (a column REVOKE leaves the other columns' grants as they are).
PROBLEM_EMBEDDING_PRIVILEGES = (
    "INSERT (embedding, embed_model, embed_version), UPDATE (embedding, embed_model, embed_version)"
)
NARROW_SQL = f"REVOKE {PROBLEM_EMBEDDING_PRIVILEGES} ON TABLE problems FROM bridge_app;"
RESTORE_SQL = f"GRANT {PROBLEM_EMBEDDING_PRIVILEGES} ON TABLE problems TO bridge_app;"

# Revision 0001's INSERT policy on developer_profiles (the own row), restored on downgrade; this revision adds that a
# profile is inserted without an embedding.
PROFILE_INSERT_0001 = "user_id = app_user_id()"
PROFILE_INSERT = (
    f"{PROFILE_INSERT_0001} AND profile_embedding IS NULL AND embed_model IS NULL AND embed_version IS NULL"
    " AND profile_embedded_at IS NULL AND profile_embedding_hash IS NULL"
)

# (table, column, type) added by this revision.
NEW_COLUMNS = (
    ("developer_profiles", "profile_embedded_at", sa.DateTime(timezone=True)),
    ("developer_profiles", "profile_embedding_hash", sa.Text()),
    ("problems", "embedded_at", sa.DateTime(timezone=True)),
    ("problems", "embedding_hash", sa.Text()),
)
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

-- The SHA-256 of an embedding's text (its UTF-8 bytes), 64 lower-case hex digits: what a vector is stored with, and
-- what the readers compare with. Internal (no EXECUTE grant).
CREATE FUNCTION embedding_text_hash(p_text text) RETURNS text
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT encode(sha256(convert_to(p_text, 'UTF8')), 'hex')
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

-- The text a problem's vector is computed from: its title and statement, each one embedding_text_line, empty parts
-- left out, joined by a newline and cut at 8,000 characters; '' when there is nothing. Internal (no EXECUTE grant).
CREATE FUNCTION problem_embedding_text(p_title text, p_statement text) RETURNS text
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT left(array_to_string(ARRAY[public.embedding_text_line(p_title), public.embedding_text_line(p_statement)],
                                E'\n'), 8000)
$$;

-- Whether a row's vector is stale: its text is not empty, and it has no vector, another model or version (left out
-- when p_model is NULL), or a stored hash that is not the text's. The one staleness rule of both tables, the readers
-- and the counts. Internal (no EXECUTE grant).
CREATE FUNCTION embedding_is_stale(p_vector_missing boolean, p_stored_model text, p_stored_version text,
                                   p_stored_hash text, p_text text, p_model text, p_version text) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT p_text <> ''
       AND (p_vector_missing
            OR (p_model IS NOT NULL
                AND (p_stored_model IS DISTINCT FROM p_model OR p_stored_version IS DISTINCT FROM p_version))
            OR p_stored_hash IS DISTINCT FROM public.embedding_text_hash(p_text))
$$;

-- The developers whose profile may be embedded, without their text (no text is built here): a profile whose user is
-- active and not staff and whose latest profiling decision is a grant, with its vector's time, whether it has no
-- vector, and its model, version and hash. Internal (no EXECUTE grant).
CREATE FUNCTION profile_embedding_candidates()
    RETURNS TABLE (user_id uuid, embedded_at timestamptz, vector_missing boolean, stored_model text,
                   stored_version text, stored_hash text)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT d.user_id, d.profile_embedded_at, d.profile_embedding IS NULL, d.embed_model::text, d.embed_version::text,
           d.profile_embedding_hash
      FROM public.developer_profiles d
      JOIN public.users u ON u.id = d.user_id
     WHERE u.status = 'active' AND u.staff_role IS NULL
       AND public.profile_consent_granted(d.user_id)
$$;

-- Every developer whose profile vector is stale (embedding_is_stale over profile_embedding_candidates): one text build
-- per candidate. The counts only. Internal (no EXECUTE grant).
CREATE FUNCTION profiles_to_embed(p_model text, p_version text) RETURNS SETOF uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT c.user_id
      FROM public.profile_embedding_candidates() c
     WHERE public.embedding_is_stale(c.vector_missing, c.stored_model, c.stored_version, c.stored_hash,
                                     public.profile_embedding_text(c.user_id), p_model, p_version)
$$;

-- Whether every signed-in developer may read p_problem now, as bridge.matching.trend_facts reads the recommendable
-- problems: published and clear; an organisation's problem only while the organisation is listed (unclaimed, E1 or E2,
-- not delisted); a Brief's problem only while its Brief is published (staff may approve the problem of a draft Brief,
-- which stays its organisation's). The Brief's deadline is a ranking filter, not a reading one, and is left to the
-- ranker. A problem is embedded only once it is readable. Internal (no EXECUTE grant).
CREATE FUNCTION problem_is_readable(p_problem uuid) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.problems p
         WHERE p.id = p_problem AND p.status = 'published' AND p.moderation_state = 'clear'
           AND (p.org_id IS NULL
                OR EXISTS (SELECT 1 FROM public.organizations o
                            WHERE o.id = p.org_id AND o.verification IN ('unclaimed', 'e1', 'e2')
                              AND o.delisted_at IS NULL))
           AND (p.source <> 'org_brief'
                OR EXISTS (SELECT 1 FROM public.problem_briefs b WHERE b.problem_id = p.id AND b.status = 'published')))
$$;

-- The problems that may be embedded (problem_is_readable), with their title and statement (the text is built by the
-- caller), the vector's time, whether there is no vector, and its model, version and hash. Internal (no EXECUTE
-- grant).
CREATE FUNCTION problem_embedding_candidates()
    RETURNS TABLE (problem_id uuid, embedded_at timestamptz, vector_missing boolean, stored_model text,
                   stored_version text, stored_hash text, title text, statement text)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT p.id, p.embedded_at, p.embedding IS NULL, p.embed_model::text, p.embed_version::text, p.embedding_hash,
           p.title::text, p.statement
      FROM public.problems p
     WHERE public.problem_is_readable(p.id)
$$;

-- Every problem whose vector is stale (embedding_is_stale over problem_embedding_candidates). The counts only.
-- Internal (no EXECUTE grant).
CREATE FUNCTION problems_to_embed(p_model text, p_version text) RETURNS SETOF uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT c.problem_id
      FROM public.problem_embedding_candidates() c
     WHERE public.embedding_is_stale(c.vector_missing, c.stored_model, c.stored_version, c.stored_hash,
                                     public.problem_embedding_text(c.title, c.statement), p_model, p_version)
$$;

-- Nulls p_user's profile vector, model, version, time and hash and moves updated_at to now(): the row is always
-- written, even when there is nothing to clear, so a writer in flight is waited for (or waits), and a writer whose
-- snapshot predates this one would meet a write conflict rather than overwrite it. Internal (no EXECUTE grant): the
-- clearer and the consents trigger, as the owner.
CREATE FUNCTION profile_embedding_clear(p_user uuid) RETURNS void
    LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    UPDATE public.developer_profiles d
       SET profile_embedding = NULL, embed_model = NULL, embed_version = NULL, profile_embedded_at = NULL,
           profile_embedding_hash = NULL, updated_at = now()
     WHERE d.user_id = p_user
$$;

-- A page of the developers whose profile vector the worker computes next (REQ-PERS-02; AC-PERS-3: only while the
-- profiling consent is granted), with the text to embed and its hash (handed back to the writer). Two stages, so a page
-- costs only the texts it looks at: first the developers without a vector (never embedded first, then the oldest
-- time, then user id; a text is built for each until the page is full, an empty one skipped), then, only while the
-- page is not full, the developers with a vector whose model or version differs or whose text changed (oldest time
-- first, then user id; one text build per embedded developer looked at). The worker only (no user bound): a signed-in
-- session learns nothing of other developers' profiles.
CREATE FUNCTION app_profiles_to_embed(p_model text, p_version text, p_limit integer)
    RETURNS TABLE (user_id uuid, text text, text_hash text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_row record;
    v_body pg_catalog.text;
    v_taken integer := 0;
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
    FOR v_row IN
        SELECT c.* FROM public.profile_embedding_candidates() c
         ORDER BY c.vector_missing DESC, c.embedded_at ASC NULLS FIRST, c.user_id
    LOOP
        EXIT WHEN v_taken >= p_limit;
        v_body := public.profile_embedding_text(v_row.user_id);
        IF public.embedding_is_stale(v_row.vector_missing, v_row.stored_model, v_row.stored_version,
                                     v_row.stored_hash, v_body, p_model, p_version) THEN
            RETURN QUERY SELECT v_row.user_id, v_body, public.embedding_text_hash(v_body);
            v_taken := v_taken + 1;
        END IF;
    END LOOP;
END;
$$;

-- Writes p_user's profile vector (REQ-PERS-02; AC-PERS-3): the worker only. The profile's row is locked first, then the
-- consent and the text read afresh, so a withdrawal in flight (its trigger locks the same row) is waited for and its
-- outcome read, and a text changed since the listing is seen; written with the model, version, now() and the hash
-- only while the latest profiling decision is a grant, the user is active and not staff, and p_text_hash is the hash
-- of the text as it reads now. Returns whether it wrote.
CREATE FUNCTION app_set_profile_embedding(p_user uuid, p_vector vector, p_model text, p_version text,
                                          p_text_hash text)
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_text text;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_set_profile_embedding: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Under REPEATABLE READ or SERIALIZABLE the consent, state and text read after the lock could predate it.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'app_set_profile_embedding: must run at READ COMMITTED isolation, not %',
            upper(current_setting('transaction_isolation')) USING ERRCODE = 'invalid_transaction_state';
    END IF;
    IF p_vector IS NULL OR vector_dims(p_vector) <> 1024 OR vector_norm(p_vector) = 0
       OR NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40))
       OR p_text_hash IS NULL OR p_text_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'app_set_profile_embedding: a non-zero vector of 1024 dimensions, a model (1 to 80 characters),'
            ' a version (1 to 40) and the text''s hash' USING ERRCODE = 'invalid_parameter_value';
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
    v_text := public.profile_embedding_text(p_user);
    IF v_text = '' OR public.embedding_text_hash(v_text) <> p_text_hash THEN
        RETURN false;
    END IF;
    UPDATE public.developer_profiles d
       SET profile_embedding = p_vector, embed_model = p_model, embed_version = p_version, profile_embedded_at = now(),
           profile_embedding_hash = p_text_hash
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

-- A page of the problems whose vector the worker computes next (REQ-EMB-01), with the text and its hash: as
-- app_profiles_to_embed, the problems without a vector first (never embedded first, then the oldest time, then id),
-- then, only while the page is not full, those with a vector whose model or version differs or whose text changed
-- (oldest time first, then id); a text is built only for the problems looked at. The worker only (no user bound).
CREATE FUNCTION app_problems_to_embed(p_model text, p_version text, p_limit integer)
    RETURNS TABLE (problem_id uuid, text text, text_hash text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_row record;
    v_body pg_catalog.text;
    v_taken integer := 0;
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
    FOR v_row IN
        SELECT c.* FROM public.problem_embedding_candidates() c
         ORDER BY c.vector_missing DESC, c.embedded_at ASC NULLS FIRST, c.problem_id
    LOOP
        EXIT WHEN v_taken >= p_limit;
        v_body := public.problem_embedding_text(v_row.title, v_row.statement);
        IF public.embedding_is_stale(v_row.vector_missing, v_row.stored_model, v_row.stored_version,
                                     v_row.stored_hash, v_body, p_model, p_version) THEN
            RETURN QUERY SELECT v_row.problem_id, v_body, public.embedding_text_hash(v_body);
            v_taken := v_taken + 1;
        END IF;
    END LOOP;
END;
$$;

-- Writes p_problem's vector (REQ-EMB-01): the worker only. The problem's row is locked, then its readability and text
-- read: written with the model, version, now() and the hash only while it is readable (problem_is_readable) and
-- p_text_hash is the hash of its text as it reads now (a hold, an archive, a Brief back in draft, a delisting or an
-- edit since it was listed writes nothing). Returns whether it wrote.
CREATE FUNCTION app_set_problem_embedding(p_problem uuid, p_vector vector, p_model text, p_version text,
                                          p_text_hash text)
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_text text;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_set_problem_embedding: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    -- Under REPEATABLE READ or SERIALIZABLE the consent, state and text read after the lock could predate it.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'app_set_problem_embedding: must run at READ COMMITTED isolation, not %',
            upper(current_setting('transaction_isolation')) USING ERRCODE = 'invalid_transaction_state';
    END IF;
    IF p_vector IS NULL OR vector_dims(p_vector) <> 1024 OR vector_norm(p_vector) = 0
       OR NOT (public.embedding_label_is_valid(p_model, 80) AND public.embedding_label_is_valid(p_version, 40))
       OR p_text_hash IS NULL OR p_text_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'app_set_problem_embedding: a non-zero vector of 1024 dimensions, a model (1 to 80 characters),'
            ' a version (1 to 40) and the text''s hash' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT public.problem_embedding_text(p.title, p.statement) INTO v_text
      FROM public.problems p WHERE p.id = p_problem FOR UPDATE;
    IF NOT FOUND OR NOT public.problem_is_readable(p_problem) THEN
        RETURN false;
    END IF;
    IF v_text = '' OR public.embedding_text_hash(v_text) <> p_text_hash THEN
        RETURN false;
    END IF;
    UPDATE public.problems p
       SET embedding = p_vector, embed_model = p_model, embed_version = p_version, embedded_at = now(),
           embedding_hash = p_text_hash
     WHERE p.id = p_problem;
    RETURN true;
END;
$$;

-- The profiles and problems holding a vector whose text is empty now (all it was computed from removed): never listed
-- (an empty text is not embedded), so app_clear_empty_embeddings clears them and the counts count them. One text build
-- per row holding a vector. Internal (no EXECUTE grant).
CREATE FUNCTION empty_embedded_profiles() RETURNS SETOF uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT d.user_id FROM public.developer_profiles d
     WHERE d.profile_embedding IS NOT NULL AND public.profile_embedding_text(d.user_id) = ''
$$;

CREATE FUNCTION empty_embedded_problems() RETURNS SETOF uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT p.id FROM public.problems p
     WHERE p.embedding IS NOT NULL AND public.problem_embedding_text(p.title, p.statement) = ''
$$;

-- Clears every vector whose text is now empty (REQ-PERS-02, REQ-EMB-01; the job calls it at the start of each run): a
-- vector computed from text that is all gone would otherwise stay, with its model, version and hash, and the ranker
-- would use it. Each row is locked and its text read again (the row lock first, then a fresh read, as the writers);
-- the vector, model, version, time and hash go. Returns how many profiles and problems it cleared. The worker only (no
-- user bound), at READ COMMITTED only.
CREATE FUNCTION app_clear_empty_embeddings() RETURNS TABLE (profiles integer, problems integer)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_id uuid;
    v_profiles integer := 0;
    v_problems integer := 0;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_clear_empty_embeddings: the embedding worker only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'app_clear_empty_embeddings: must run at READ COMMITTED isolation, not %',
            upper(current_setting('transaction_isolation')) USING ERRCODE = 'invalid_transaction_state';
    END IF;
    FOR v_id IN SELECT e.id FROM public.empty_embedded_profiles() AS e(id) LOOP
        PERFORM 1 FROM public.developer_profiles d WHERE d.user_id = v_id FOR UPDATE;
        IF public.profile_embedding_text(v_id) = '' THEN
            UPDATE public.developer_profiles d
               SET profile_embedding = NULL, embed_model = NULL, embed_version = NULL, profile_embedded_at = NULL,
                   profile_embedding_hash = NULL
             WHERE d.user_id = v_id AND d.profile_embedding IS NOT NULL;
            v_profiles := v_profiles + 1;
        END IF;
    END LOOP;
    FOR v_id IN SELECT e.id FROM public.empty_embedded_problems() AS e(id) LOOP
        PERFORM 1 FROM public.problems p WHERE p.id = v_id FOR UPDATE;
        IF (SELECT public.problem_embedding_text(p.title, p.statement) FROM public.problems p WHERE p.id = v_id) = ''
        THEN
            UPDATE public.problems p
               SET embedding = NULL, embed_model = NULL, embed_version = NULL, embedded_at = NULL, embedding_hash = NULL
             WHERE p.id = v_id AND p.embedding IS NOT NULL;
            v_problems := v_problems + 1;
        END IF;
    END LOOP;
    RETURN QUERY SELECT v_profiles, v_problems;
END;
$$;

-- How many rows the two readers would list, and how many vectors app_clear_empty_embeddings would clear (the embedding
-- job's log line): the worker only. With a model and version (both or neither) the model rule applies; without, rows
-- with no vector or whose text changed since.
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
    SELECT (SELECT count(*) FROM public.profiles_to_embed(p_model, p_version))
           + (SELECT count(*) FROM public.empty_embedded_profiles()),
           (SELECT count(*) FROM public.problems_to_embed(p_model, p_version))
           + (SELECT count(*) FROM public.empty_embedded_problems());
END;
$$;

-- AC-PERS-3 at the database: a profiling decision that is not a grant clears the profile's vector in its own
-- transaction, whatever the application does next (it also calls app_clear_profile_embedding). For every role (the
-- trigger's WHEN names the rows). SECURITY DEFINER: bridge_app holds no UPDATE of the vector.
CREATE FUNCTION consents_profiling_withdrawn() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    PERFORM public.profile_embedding_clear(NEW.user_id);
    RETURN NULL;
END;
$$;

-- A consent decision's time is the database's for every writer but the table's owner (a seed or a backfill keeps its
-- own): the latest decision (created_at, then id) is then the last inserted, whatever a client sends, so a
-- future-dated grant cannot outlive a later withdrawal. SECURITY INVOKER: current_user is the writer (as
-- engagement_notes_redaction_guard() of revision 0006).
CREATE FUNCTION consents_created_now() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF current_user <> (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
    THEN
        NEW.created_at := now();
    END IF;
    RETURN NEW;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_profiles_to_embed(text, text, integer)": ("bridge_app",),  # the worker, no user bound
    "app_set_profile_embedding(uuid, vector, text, text, text)": ("bridge_app",),  # the worker, no user bound
    "app_clear_profile_embedding(uuid)": ("bridge_app",),  # the worker, or the user's own opt-out
    "app_problems_to_embed(text, text, integer)": ("bridge_app",),  # the worker, no user bound
    "app_set_problem_embedding(uuid, vector, text, text, text)": ("bridge_app",),  # the worker, no user bound
    "app_stale_embedding_counts(text, text)": ("bridge_app",),  # the worker's log line, no user bound
    "app_clear_empty_embeddings()": ("bridge_app",),  # the worker at the start of each run, no user bound
}
INTERNAL_FUNCTIONS = (
    "profile_embedding_clear(uuid)",
    "profiles_to_embed(text, text)",
    "problems_to_embed(text, text)",
    "profile_embedding_candidates()",
    "problem_embedding_candidates()",
    "embedding_is_stale(boolean, text, text, text, text, text, text)",
    "empty_embedded_profiles()",
    "empty_embedded_problems()",
    "problem_embedding_text(text, text)",
    "problem_is_readable(uuid)",
    "profile_embedding_text(uuid)",
    "profile_consent_granted(uuid)",
    "embedding_text_hash(text)",
    "embedding_text_line(text)",
    "embedding_label_is_valid(text, integer)",
)
TRIGGER_FUNCTIONS = ("consents_profiling_withdrawn()", "consents_created_now()")

TRIGGERS_SQL = r"""
CREATE TRIGGER consents_profiling_withdrawn
    AFTER INSERT ON consents
    FOR EACH ROW WHEN (NEW.purpose = 'profiling' AND NOT NEW.granted)
    EXECUTE FUNCTION consents_profiling_withdrawn();
CREATE TRIGGER consents_created_now
    BEFORE INSERT ON consents
    FOR EACH ROW EXECUTE FUNCTION consents_created_now();
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants = [NARROW_SQL]
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    for table, column, type_ in NEW_COLUMNS:
        op.add_column(table, sa.Column(column, type_, nullable=True))
    for name, table, column in INDEXES:
        op.create_index(
            name, table, [column], unique=False, postgresql_using="hnsw", postgresql_ops={column: "vector_cosine_ops"}
        )
    _run_sql(FUNCTIONS_SQL)
    _run_sql(TRIGGERS_SQL)
    _run_sql(f"ALTER POLICY bridge_app_insert ON developer_profiles WITH CHECK ({PROFILE_INSERT});")
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Derived data only, so it proceeds with rows: every profile's and problem's vector, model and version is nulled
    (the worker recomputes them from rows that stay, after a re-upgrade; once the hashes go nothing would say which
    text a vector came from), then the times, the hashes, the indexes, the functions and the trigger go. bridge_app's
    INSERT and UPDATE of problems' embedding columns (revisions 0002 and 0005) are granted again, and revision 0001's
    INSERT policy of developer_profiles is restored (first: it names the columns that go)."""
    _run_sql(
        "UPDATE developer_profiles SET profile_embedding = NULL, embed_model = NULL, embed_version = NULL"
        " WHERE profile_embedding IS NOT NULL OR embed_model IS NOT NULL OR embed_version IS NOT NULL;"
        " UPDATE problems SET embedding = NULL, embed_model = NULL, embed_version = NULL"
        " WHERE embedding IS NOT NULL OR embed_model IS NOT NULL OR embed_version IS NOT NULL;"
    )
    _run_sql(f"ALTER POLICY bridge_app_insert ON developer_profiles WITH CHECK ({PROFILE_INSERT_0001});")
    _run_sql("DROP TRIGGER consents_profiling_withdrawn ON consents; DROP TRIGGER consents_created_now ON consents;")
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )
    for name, table, _column in reversed(INDEXES):
        op.drop_index(name, table_name=table)
    for table, column, _type in reversed(NEW_COLUMNS):
        op.drop_column(table, column)
    _run_sql(RESTORE_SQL)
