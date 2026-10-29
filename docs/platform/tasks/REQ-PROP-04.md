# REQ-PROP-04

- Task: T2.9 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-ai
- Files owned: `bridge/proposals/originality.py`, `bridge/jobs/tier2_similarity.py`
- Depends on: T2.2, T2.3.

## Scope

Originality check, informational and never blocking, ≤10 per developer per day (`originality_checks`): MinHash LSH (5-word shingles, Jaccard ≥0.8) and bge-m3 cosine ≥0.88 of the submitter's text against other owners' Tier-1 teasers and teaser embeddings only; coarse bands (`none`, `some_overlap`, `high_overlap`), never numeric scores, never another owner's text beyond Tier 1; the optional Sonnet explainer sees only the submitter's text and others' Tier 1 (fake/cassette in CI). Moderator-only Tier-2-vs-Tier-2 job (cosine ≥0.95, different owner, later timestamp) under `tier2_moderation`, writing `moderation_cases` (`tier2_similarity`); its result reaches no developer.

## Acceptance criteria and tests

AC-PROP-4 (`unit/proposals/test_originality.py`: two fixtures differing only in Tier-2 fields give byte-identical responses over 50 variations; no numeric score or Tier-2 text).
