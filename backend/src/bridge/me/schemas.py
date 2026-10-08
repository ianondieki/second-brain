"""The command palette's results and the activity calendar as the API returns them (REQ-UX-01, REQ-UX-05; P25-B).

A search item carries only what a list screen already shows the caller: its title, one line under it (a niche, an
organisation's name, a stage, an organisation type and county) and the web app path it opens. The calendar carries
counts only: never a record, a title or another person.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SearchKind = Literal["ideas", "engagements", "inbox", "problems", "briefs", "companies"]
ActivityKind = Literal[
    "version_registered",
    "proposal_published",
    "engagement_step",
    "message_sent",
    "quiz_answered",
    "team_message",
    "proposal_opened",
    "brief_posted",
]
NAIROBI_ZONE = "Africa/Nairobi"


class SearchItem(BaseModel):
    id: str = Field(description="The record's id (an Inbox item's is its pitch, as the Inbox's tag_id)")
    title: str
    subtitle: str | None = Field(description="One line under the title, as the list screens show it; may be null")
    href: str = Field(
        description="The web app path the item opens; an organisation's items keep ?org= for a member of several"
    )


class SearchGroup(BaseModel):
    kind: SearchKind
    items: list[SearchItem] = Field(
        description="At most five: a title (or name) starting with the words first, then the newest"
    )


class SearchResults(BaseModel):
    q: str = Field(description="The words searched for, trimmed")
    groups: list[SearchGroup] = Field(description="The caller's side's groups that found something, in a fixed order")


class ActivityDay(BaseModel):
    date: dt.date = Field(description="A day in Africa/Nairobi")
    count: int = Field(description="The caller's own actions that day, every kind together")


class ActivityKindCount(BaseModel):
    kind: ActivityKind
    count: int = Field(description="The caller's own actions of this kind over the whole range")


class ActivityCalendar(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: dt.date = Field(alias="from", description="The first day of the range (Africa/Nairobi)")
    to: dt.date = Field(description="The last day: today on the platform clock (Africa/Nairobi)")
    timezone: Literal["Africa/Nairobi"]
    days: list[ActivityDay] = Field(description="Every day of the range, oldest first, days without actions as 0")
    kinds: list[ActivityKindCount] = Field(description="Each kind counted for the caller's side, in a fixed order")
    total: int = Field(description="Every counted action over the range")
