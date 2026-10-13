"""REQ-FND-04 (P28 track PD, AT-PD-5, unit half): the public demo's content scope. With
``PUBLIC_DEMO_CONTENT=fictional`` the seed skips the provisional directory of real organisations and every seeded
research card that cites an excerpt whose ``source_type`` is not ``official`` (all of them today), and every reader
of the saved excerpts at run time (``catalogue_for``: the admin API, the research job, the demo seed) sees only the
official ones; ``full``, and the mode off, change nothing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from bridge import public_demo
from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.problems.research import checks
from bridge.problems.research.policy import get_research_policy
from bridge.problems.research.runtime import ResearchRuntime
from bridge.problems.research.sources import Catalogue, catalogue_for, get_catalogue, load_catalogue, official_only
from bridge.seed.demo.research import (
    OFFICIAL_ANSWERS,
    SEEDED_ANSWERS,
    answers_for,
    left_out,
    niches_to_seed,
    seeded_answer,
    seeded_niches,
)
from bridge.seed.directory import DirectorySeedRefused, directory_refusal, ensure_loadable

AS_OF = date(2026, 10, 13)  # the card's day: the SACCO excerpts are fresh, ke-agr-004 and ke-tel-005 archived


def public(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


def test_fictional_only_is_the_public_demo_with_fictional_content() -> None:
    assert public_demo.fictional_only(public())
    assert not public_demo.fictional_only(public(public_demo_content="full"))
    assert not public_demo.fictional_only(get_settings())
    assert not public_demo.fictional_only(get_settings().model_copy(update={"public_demo_content": "fictional"}))


def test_the_fictional_public_demo_skips_the_provisional_directory() -> None:
    reason = directory_refusal(public())
    assert reason is not None
    assert reason.startswith("PUBLIC_DEMO=true with PUBLIC_DEMO_CONTENT=fictional")
    with pytest.raises(DirectorySeedRefused, match="fictional fixture organisations"):
        ensure_loadable(public())
    assert directory_refusal(public(public_demo_content="full")) is None
    assert directory_refusal(get_settings()) is None


def test_the_fictional_public_demo_leaves_out_every_card_citing_a_news_excerpt() -> None:
    catalogue = load_catalogue()
    for niche in seeded_niches():  # today each seeded card cites at least one non-official excerpt
        cited = [catalogue.get(i) for i, _ in SEEDED_ANSWERS[niche]["citations"]]
        assert any(e is not None and e.source_type != "official" for e in cited), niche
    assert answers_for(public(), catalogue) == OFFICIAL_ANSWERS  # the public demo's own cards in their place
    assert niches_to_seed(public(), catalogue) == ("microfinance-saccos",)
    assert left_out(public()) == seeded_niches()
    for settings in (public(public_demo_content="full"), get_settings()):  # today's seed, exactly
        assert answers_for(settings, catalogue) is SEEDED_ANSWERS
        assert niches_to_seed(settings, catalogue) == seeded_niches()
        assert left_out(settings) == ()


def test_a_seeded_card_citing_official_excerpts_only_is_kept() -> None:
    catalogue = load_catalogue()
    official = Catalogue(tuple(replace(e, source_type="official") for e in catalogue.excerpts), catalogue.allowlists)
    answers = answers_for(public(), official)
    assert tuple(answers) == seeded_niches()
    assert answers["microfinance-saccos"] is OFFICIAL_ANSWERS["microfinance-saccos"]  # the official card wins
    assert all(answers[n] is SEEDED_ANSWERS[n] for n in seeded_niches() if n not in OFFICIAL_ANSWERS)
    one_news = Catalogue(
        tuple(replace(e, source_type="news") if e.id == "ke-tel-001" else e for e in official.excerpts),
        catalogue.allowlists,
    )
    assert "networks-telecommunications" not in niches_to_seed(public(), one_news)


@pytest.mark.parametrize("niche", sorted(OFFICIAL_ANSWERS))
def test_every_official_card_passes_the_checks_on_official_excerpts_alone(niche: str) -> None:
    """Each public demo card cites official excerpts only, passes every check in code on what a fictional run sends
    (the official excerpts that are not archived), and names no organisation."""
    catalogue, policy = official_only(load_catalogue()), get_research_policy()
    sent = {e.id: e for e in catalogue.usable(niche, "KE", AS_OF, policy)}
    assert len(sent) >= policy.min_excerpts  # a run of the niche is not stopped for not_enough_excerpts
    [draft] = seeded_answer(niche, OFFICIAL_ANSWERS).problems
    assert {c.excerpt_id for c in draft.citations} <= set(sent)
    verdict = checks.check_draft(draft.draft(), sent, catalogue.allowlists["KE"], policy, AS_OF)
    assert isinstance(verdict, checks.Accepted), verdict
    assert verdict.agreement == 1
    assert verdict.text.named_orgs == ()
    assert verdict.confidence >= policy.discard_below
    assert draft.county_code is None


def test_the_official_cards_are_every_niche_the_official_excerpts_support() -> None:
    """A niche gets a public demo card exactly when its official excerpts let a run start: at least ``min_excerpts``
    that are not archived. Agriculture has one (its second is archived), the telecoms one is archived and health has
    none, so only microfinance-saccos qualifies today."""
    catalogue, policy = official_only(load_catalogue()), get_research_policy()
    supported = {
        n for n in catalogue.niches("KE") if len(catalogue.usable(n, "KE", AS_OF, policy)) >= policy.min_excerpts
    }
    assert supported == set(OFFICIAL_ANSWERS) == {"microfinance-saccos"}


def test_runtime_readers_see_only_official_excerpts_in_the_fictional_public_demo() -> None:
    full = get_catalogue()
    fictional = catalogue_for(public())
    assert {e.source_type for e in fictional.excerpts} == {"official"}
    assert [e.id for e in fictional.excerpts] == [e.id for e in full.excerpts if e.source_type == "official"]
    assert (len(fictional.excerpts), len(full.excerpts)) == (6, 19)
    assert fictional.allowlists == full.allowlists  # the allowed domains are listed; only excerpt text is withheld
    assert fictional.niches("KE") == ("agriculture", "microfinance-saccos", "networks-telecommunications")
    assert catalogue_for(public()) is fictional  # built once per process
    assert catalogue_for(public(public_demo_content="full")) == full
    assert catalogue_for(get_settings()) == full


def test_official_only_keeps_official_excerpts_and_the_allowlists() -> None:
    full = get_catalogue()
    assert official_only(full).excerpts == tuple(e for e in full.excerpts if e.official)
    assert official_only(official_only(full)) == official_only(full)


@pytest.mark.parametrize(("content", "count"), [("fictional", 6), ("full", 19)])
def test_the_research_job_reads_the_same_catalogue(content: str, count: int) -> None:
    factory = create_session_factory(create_engine("postgresql+psycopg://probe@localhost:1/probe"))
    runtime = ResearchRuntime(public(public_demo_content=content), factory=factory, client=lambda db: NotImplemented)
    assert len(runtime.deps().catalogue.excerpts) == count
