"""Peers and team up: the API's bodies and views (REQ-DEV-03; D-58, D-62).

Another developer is shown only as their card (``DeveloperCard``: id, handle, headline) or a peer row (with the county's
name and the shared liked niches), read through revision 0011's definers; never an email, phone, name, bio or
verification level. A note and a message are plain text as typed (``bridge.teams.text``): render them as text, never
as markup, and never auto-link them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bridge.teams.models import MESSAGE_MAX_CHARS, NOTE_MAX_CHARS
from bridge.teams.text import RAW_MESSAGE_MAX_CHARS, RAW_NOTE_MAX_CHARS, clean_message, clean_note

InvitationStatus = Literal["pending", "accepted", "declined", "withdrawn", "ended"]
# What the caller is told of a closed thread: "left" (a party left it), "blocked" (the caller blocked the other) or
# "ended" (the other party blocked the caller: never said as such; the 0011 security review's MINOR 1).
ShownCloseReason = Literal["left", "blocked", "ended"]
ReportReason = Literal["spam", "abuse", "contact_details", "confidential", "other"]  # revision 0008's codes


class DeveloperCard(BaseModel):
    """Another developer as a peer or counterpart sees them (``app_developer_card``)."""

    user_id: UUID
    handle: str
    headline: str | None


class PeerOut(BaseModel):
    user_id: UUID = Field(description="Pass as to_user_id to invite them")
    handle: str
    headline: str | None
    county_name: str | None = Field(description="Their county's name, when they gave one")
    shared_niches: list[str] = Field(description="Slugs of the liked niches you share, sorted")
    same_county: bool = Field(description="They are in your county")


class PeersPage(BaseModel):
    """A page of peers (20 at most): the most shared niches first, then your county, then the newest to opt in."""

    peers: list[PeerOut]
    next: int | None = Field(description="Pass as ?page= for the next page; null on the last")
    opted_in: bool = Field(description="False: you have not turned Peers on, so the list is empty")


class TeamProblemOut(BaseModel):
    id: UUID
    title: str | None = Field(description="Null when the problem is no longer published")


class InvitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_user_id: UUID = Field(description="A peer from GET /api/me/peers, or a developer you team up with")
    problem_id: UUID = Field(description="A published problem or a public, published Problem Brief")
    note: str | None = Field(
        default=None,
        max_length=RAW_NOTE_MAX_CHARS,
        description=f"At most {NOTE_MAX_CHARS} characters of plain text; line breaks allowed",
    )

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return clean_note(value)


class InvitationOut(BaseModel):
    id: UUID
    direction: Literal["received", "sent"]
    status: InvitationStatus
    counterpart: DeveloperCard | None = Field(description="The other developer; null when you may no longer see them")
    problem: TeamProblemOut
    note: str | None
    created_at: datetime
    decided_at: datetime | None


class InvitationsOut(BaseModel):
    """Pending invitations, newest first."""

    received: list[InvitationOut]
    sent: list[InvitationOut]


class AcceptedOut(BaseModel):
    thread_id: UUID


class ThreadSummaryOut(BaseModel):
    id: UUID
    counterpart: DeveloperCard | None = Field(description="The other developer; null when you may no longer see them")
    problem: TeamProblemOut
    created_at: datetime
    last_message_at: datetime | None
    unread: int = Field(ge=0, description="Messages by the other developer after your read marker")
    open: bool
    closed_at: datetime | None
    closed_reason: ShownCloseReason | None = Field(
        description="left: a party left; blocked: you blocked them; ended: the thread was ended for you"
    )


class ThreadsOut(BaseModel):
    """Open threads first, then closed ones; each newest activity first."""

    threads: list[ThreadSummaryOut]


class TeamMessageOut(BaseModel):
    id: UUID
    mine: bool = Field(description="You wrote it")
    body: str = Field(description="Plain text as typed: render it as text, never as markup, and never auto-link it")
    redacted: bool
    created_at: datetime


class ThreadOut(BaseModel):
    """One page of a thread: the first page holds the newest messages and ``next_cursor`` the older ones; within a page
    the messages are oldest first."""

    thread: ThreadSummaryOut
    can_post: bool = Field(description="The thread is open")
    max_chars: int = MESSAGE_MAX_CHARS
    last_read_at: datetime | None
    items: list[TeamMessageOut]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the older page; null on the oldest")


class TeamMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(
        min_length=1,
        max_length=RAW_MESSAGE_MAX_CHARS,
        description=f"1 to {MESSAGE_MAX_CHARS} characters of plain text; line breaks allowed",
    )

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return clean_message(value)


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    up_to: UUID | None = Field(default=None, description="The newest message you have seen; omit it for all")


class ReadOut(BaseModel):
    unread: int = Field(ge=0)
    last_read_at: datetime | None


class TeamReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasons: list[ReportReason] = Field(min_length=1, max_length=5)

    @field_validator("reasons")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class TeamReportOut(BaseModel):
    case_id: UUID


class UnreadCountOut(BaseModel):
    unread: int = Field(ge=0, description="Unread messages over all your team threads")


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class BlockedOut(BaseModel):
    user_id: UUID
    handle: str
    blocked_at: datetime


class BlocksOut(BaseModel):
    """Your blocks, newest first."""

    blocked: list[BlockedOut]


class ContributorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID = Field(description="The other developer of one of your team threads")


class ContributorOut(BaseModel):
    user_id: UUID
    handle: str = Field(description="The handle the idea and its certificate show")
    added_at: datetime


class ContributorsOut(BaseModel):
    """An idea's contributors as its owner manages them (D-62 (a)), by the time they were added."""

    contributors: list[str] = Field(description='The handles the idea and its certificate show ("Contributors: ...")')
    items: list[ContributorOut]


class ContributionOut(BaseModel):
    proposal_id: UUID
    title: str | None = Field(description="Null while the idea is not published")
    added_at: datetime


class ContributionsOut(BaseModel):
    """The ideas that credit you as a contributor, newest first."""

    items: list[ContributionOut]
