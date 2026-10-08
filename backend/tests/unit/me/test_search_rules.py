"""REQ-UX-01 (P25-B, D-67): the command palette's search rules without a database.

Given what was typed, when it is checked, then 2 to 80 characters once trimmed pass and anything else is 422
``invalid_query`` without quoting it; LIKE's ``%``, ``_`` and ``\\`` match themselves; each side searches its own
groups in a fixed order (companies for developers only; a member with no open organisation only problems); every item
links to the web app's path for it, an organisation's with ``?org=`` only for a member of several; each group is cut
to five and empty groups are left out; and each statement repeats its list's own rule (the owner, the party, the
delivered tag of a published proposal, the organisation's Briefs, ``problem_is_readable``, the directory's listing).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Select, create_engine

from bridge.errors import ApiError
from bridge.me import search
from bridge.me.caller import Caller
from bridge.me.schemas import SearchItem
from bridge.models.enums import EngagementState, OrgKind

USER = UUID(int=1)
DIALECT = create_engine("postgresql+psycopg://").dialect  # nothing connects
ORG_A, ORG_B = UUID(int=0xA), UUID(int=0xB)
RECORD = UUID("01890000-0000-7000-8000-000000000042")
DEVELOPER = Caller(USER, "developer")
MEMBER = Caller(USER, "org", (ORG_A,))
MEMBER_OF_SEVERAL = Caller(USER, "org", (ORG_A, ORG_B), several=True)
STAFF = Caller(USER, "staff")


def sql(statement: Select[Any]) -> str:
    return " ".join(str(statement.compile(dialect=DIALECT)).split())


def params(statement: Select[Any]) -> dict[str, object]:
    return dict(statement.compile(dialect=DIALECT).params)


# --- what was typed --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "term"),
    [
        ("sa", "sa"),
        ("  sacco  ", "sacco"),
        ("x" * 80, "x" * 80),
        (" " + "y" * 80 + "\t", "y" * 80),
        ("Ñairobi", "Ñairobi"),
    ],
)
def test_two_to_eighty_characters_once_trimmed_are_searched(typed: str, term: str) -> None:
    assert search.normalise(typed) == term


@pytest.mark.parametrize("typed", ["", " ", "a", "  a  ", "x" * 81, "ab\x00", "ab\ncd", "a\u200b"])
def test_anything_else_is_a_422_that_does_not_quote_it(typed: str) -> None:
    with pytest.raises(ApiError) as refused:
        search.normalise(typed)
    detail: Any = refused.value.detail
    assert refused.value.status_code == 422
    assert detail == {"code": "invalid_query", "message": search.QUERY_RULE}


@pytest.mark.parametrize(
    ("term", "escaped"),
    [
        ("100%", "100\\%"),
        ("snake_case", "snake\\_case"),
        ("back\\slash", "back\\\\slash"),
        ("%_\\", "\\%\\_\\\\"),
        ("plain words", "plain words"),
    ],
)
def test_like_wildcards_and_the_escape_match_themselves(term: str, escaped: str) -> None:
    assert search.escape_like(term) == escaped
    words = search.Words(term)
    assert (words.anywhere, words.start) == (f"%{escaped}%", f"{escaped}%")


def test_the_match_and_the_order_name_the_escape_character() -> None:
    statement = search.companies_statement(DEVELOPER, search.Words("50%_off"))
    text = sql(statement)
    assert text.count("ILIKE") == 2
    assert text.count("ESCAPE '") == 2  # the backslash (doubled by an unconnected dialect, single on a server)
    values = list(params(statement).values())
    assert "%50\\%\\_off%" in values
    assert "50\\%\\_off%" in values


# --- groups by side ---------------------------------------------------------------------------------------------------


def test_each_side_searches_its_own_groups_in_order() -> None:
    assert search.kinds_for(DEVELOPER) == ("ideas", "engagements", "problems", "companies")
    assert search.kinds_for(MEMBER) == ("inbox", "engagements", "briefs", "problems")
    assert search.kinds_for(STAFF) == ("problems",)  # no Companies screen outside the developer portal


def test_a_member_whose_organisations_all_need_a_second_factor_searches_only_what_everyone_reads() -> None:
    assert search.kinds_for(Caller(USER, "org", ())) == ("problems",)


def item(n: int) -> SearchItem:
    return SearchItem(id=str(n), title=f"T{n}", subtitle=None, href=f"/x/{n}")


def test_groups_are_cut_to_five_and_empty_ones_left_out() -> None:
    found = search.results(
        "sa", [("ideas", []), ("engagements", [item(n) for n in range(7)]), ("companies", [item(9)])]
    )
    assert found.q == "sa"
    assert [group.kind for group in found.groups] == ["engagements", "companies"]
    assert [entry.id for entry in found.groups[0].items] == ["0", "1", "2", "3", "4"]
    assert search.results("sa", [("ideas", []), ("problems", [])]).groups == []


# --- links ------------------------------------------------------------------------------------------------------------


def test_each_item_links_to_its_screen_in_the_web_app() -> None:
    assert search.idea_href(RECORD) == f"/dev/ideas/{RECORD}"
    assert search.engagement_href(DEVELOPER, RECORD, ORG_A) == f"/dev/engagements/{RECORD}"
    assert search.engagement_href(MEMBER, RECORD, ORG_A) == f"/org/engagements/{RECORD}"
    assert search.inbox_href(MEMBER, RECORD, ORG_A) == f"/org/inbox/{RECORD}"
    assert search.brief_href(MEMBER, RECORD, ORG_A) == f"/org/problems/{RECORD}"
    assert search.problem_href(RECORD) == f"/problems/{RECORD}"
    assert search.company_href(RECORD) == f"/dev/companies/{RECORD}"


def test_a_member_of_several_organisations_keeps_the_organisation_on_its_links() -> None:
    assert search.org_query(MEMBER, ORG_A) == ""
    assert search.org_query(MEMBER_OF_SEVERAL, ORG_B) == f"?org={ORG_B}"
    assert search.engagement_href(MEMBER_OF_SEVERAL, RECORD, ORG_B) == f"/org/engagements/{RECORD}?org={ORG_B}"
    assert search.inbox_href(MEMBER_OF_SEVERAL, RECORD, ORG_A) == f"/org/inbox/{RECORD}?org={ORG_A}"
    assert search.brief_href(MEMBER_OF_SEVERAL, RECORD, ORG_B) == f"/org/problems/{RECORD}?org={ORG_B}"


# --- items ------------------------------------------------------------------------------------------------------------


def test_items_carry_the_title_one_line_and_the_link() -> None:
    idea = search.idea_item(DEVELOPER, SimpleNamespace(id=RECORD, title="Float alerts", niche="SACCOs", parent="Fin"))
    assert idea.model_dump() == {
        "id": str(RECORD),
        "title": "Float alerts",
        "subtitle": "Fin › SACCOs",
        "href": f"/dev/ideas/{RECORD}",
    }
    bare = search.problem_item(STAFF, SimpleNamespace(id=RECORD, title="Queues", niche=None, parent=None))
    assert (bare.subtitle, bare.href) == (None, f"/problems/{RECORD}")


def test_an_engagement_says_who_with_and_the_stage_to_the_developer_and_the_stage_to_members() -> None:
    row = SimpleNamespace(
        id=RECORD, org_id=ORG_B, state=EngagementState.UNDER_REVIEW, title=None, org_name="SACCO B (fixture)"
    )
    mine = search.engagement_item(DEVELOPER, row)
    assert (mine.title, mine.subtitle) == (search.PROPOSAL_FALLBACK, "SACCO B (fixture) · Under review")
    theirs = search.engagement_item(MEMBER_OF_SEVERAL, row)
    assert (theirs.subtitle, theirs.href) == ("Under review", f"/org/engagements/{RECORD}?org={ORG_B}")
    unnamed = search.engagement_item(DEVELOPER, SimpleNamespace(**{**vars(row), "org_name": None, "state": "CLOSED"}))
    assert unnamed.subtitle == "Organisation · Project closed"


def test_inbox_briefs_and_companies_items() -> None:
    pitched = SimpleNamespace(id=RECORD, proposal_id=UUID(int=7), org_id=ORG_A, title="T", niche="N", parent=None)
    assert search.inbox_item(MEMBER, pitched).model_dump() == {
        "id": str(RECORD),
        "title": "T",
        "subtitle": "N",
        "href": f"/org/inbox/{UUID(int=7)}",
    }
    brief = search.brief_item(
        MEMBER_OF_SEVERAL, SimpleNamespace(id=RECORD, org_id=ORG_A, title="B", niche=None, parent=None)
    )
    assert brief.href == f"/org/problems/{RECORD}?org={ORG_A}"
    company = SimpleNamespace(id=ORG_B, legal_name="SACCO B", kind=OrgKind.SACCO_MFI, county="Nakuru")
    assert search.company_item(DEVELOPER, company).subtitle == "SACCO/MFI · Nakuru"
    assert search.company_item(DEVELOPER, SimpleNamespace(**{**vars(company), "county": None})).subtitle == "SACCO/MFI"


# --- each statement repeats its list's rule -------------------------------------------------------------------------


def test_ideas_are_the_callers_own_proposals_drafts_included() -> None:
    statement = search.ideas_statement(DEVELOPER, search.Words("sa"))
    text = sql(statement)
    assert "proposals.owner_id = %(owner_id_1)s::UUID" in text
    assert "coalesce(proposal_versions_1.title, proposal_versions_2.title)" in text
    assert "status" not in text.split("WHERE", 1)[1]  # drafts, published and hidden alike, as My ideas
    assert params(statement)["owner_id_1"] == USER
    assert "LIMIT %(param_1)s" in text
    assert params(statement)["param_1"] == search.GROUP_SIZE


def test_engagements_are_the_developers_own_or_the_members_organisations() -> None:
    mine = sql(search.engagements_statement(DEVELOPER, search.Words("sa")))
    assert "engagements.developer_id = %(developer_id_1)s::UUID" in mine
    assert "organizations.legal_name ILIKE" in mine  # the counterpart's name, for the developer
    theirs = search.engagements_statement(MEMBER_OF_SEVERAL, search.Words("sa"))
    text = sql(theirs)
    assert "engagements.org_id IN (__[POSTCOMPILE_org_id_1])" in text
    assert "developer_id =" not in text
    assert "organizations.legal_name ILIKE" not in text
    assert params(theirs)["org_id_1"] == [ORG_A, ORG_B]


def test_the_inbox_is_delivered_tags_of_published_clear_proposals_of_the_members_organisations() -> None:
    statement = search.inbox_statement(MEMBER, search.Words("sa"))
    text = sql(statement)
    assert "tags.org_id IN (__[POSTCOMPILE_org_id_1])" in text
    values = set(map(str, params(statement).values()))
    assert {"delivered", "published", "clear"} <= values
    assert "proposals.current_version_id" in text


def test_briefs_are_the_members_organisations_own() -> None:
    statement = search.briefs_statement(MEMBER, search.Words("sa"))
    assert "problem_briefs.org_id IN (__[POSTCOMPILE_org_id_1])" in sql(statement)
    assert params(statement)["org_id_1"] == [ORG_A]


def test_problems_are_the_readable_ones_and_not_the_members_own_briefs() -> None:
    for caller in (DEVELOPER, STAFF, MEMBER):
        text = sql(search.problems_statement(caller, search.Words("sa")))
        assert "problems.status = %(status_1)s" in text
        assert "problems.moderation_state = %(moderation_state_1)s" in text
        assert "problem_briefs_1.visibility" in text  # a Brief's only while it is published and public
    assert "NOT IN" in sql(search.problems_statement(MEMBER, search.Words("sa")))
    assert "NOT IN" not in sql(search.problems_statement(DEVELOPER, search.Words("sa")))
    assert "NOT IN" not in sql(search.problems_statement(Caller(USER, "org", ()), search.Words("sa")))


def test_companies_are_listed_organisations() -> None:
    statement = search.companies_statement(STAFF, search.Words("sa"))
    text = sql(statement)
    assert "organizations.verification IN (__[POSTCOMPILE_verification_1])" in text
    assert "organizations.delisted_at IS NULL" in text
