"""The engagement thread's API bodies and views (REQ-ENG-11, AC-TRACK-9; docs/spec/06 6.9 "Messages tab").

A message is plain text as a party typed it: the API never renders, links or interprets it (a link stays text for the
other side). Line feeds and tabs are the only control characters a body may hold; a carriage return before a line feed
is dropped. Files are sent by id after a staged upload (``POST .../messages/attachments``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bridge.engagements.models import MAX_MESSAGE_ATTACHMENT_BYTES, MAX_MESSAGE_ATTACHMENTS, MESSAGE_MAX_CHARS
from bridge.engagements.schemas import LINES
from bridge.models.enums import AvStatus, EngagementParty, EngagementState


class ThreadStatus(StrEnum):
    NOT_OPEN = "not_open"  # the engagement has not reached INTEREST_CONFIRMED (the organisation is refused: 403)
    OPEN = "open"
    READ_ONLY = "read_only"  # the engagement ended: the parties read, nobody posts


# A report's reasons (revision 0008: app_report_message takes these codes, never free text). [[COPY-REVIEW]] labels
# are the web app's.
ReportReason = Literal["spam", "abuse", "contact_details", "confidential", "other"]


class MessageBody(BaseModel):
    """A message: 1 to 4,000 characters of plain text, not blank, and up to 5 staged uploads (ids) sent with it."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MESSAGE_MAX_CHARS, pattern=LINES)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=MAX_MESSAGE_ATTACHMENTS)

    @field_validator("body", mode="before")
    @classmethod
    def _line_feeds(cls, value: object) -> object:
        return value.replace("\r\n", "\n") if isinstance(value, str) else value

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a message is not blank")
        return value

    @field_validator("attachment_ids")
    @classmethod
    def _distinct(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("each file is sent once")
        return value


class ReadBody(BaseModel):
    """Mark the thread read up to one of its messages (its time), or up to now when ``up_to`` is left out."""

    model_config = ConfigDict(extra="forbid")

    up_to: UUID | None = Field(default=None, description="The newest message the caller has seen")


class ReportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasons: list[ReportReason] = Field(min_length=1, max_length=5)

    @field_validator("reasons")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class MessageAttachmentOut(BaseModel):
    """A file sent with a message (always ``clean``: only scanned, clean files are sent)."""

    id: UUID
    file_name: str
    content_type: str
    size_bytes: int


class MessageOut(BaseModel):
    id: UUID
    sender_party: EngagementParty
    sender_name: str = Field(description="The sender's display name, as the tracker names the parties")
    mine: bool = Field(description="The caller wrote it")
    body: str = Field(description="Plain text as typed: render it as text, never as markup, and never auto-link it")
    redacted: bool = Field(description="Staff redacted the text (D-54): body is the fixed marker")
    created_at: datetime
    attachments: list[MessageAttachmentOut]


class ThreadLimits(BaseModel):
    max_chars: int = MESSAGE_MAX_CHARS
    max_attachments: int = MAX_MESSAGE_ATTACHMENTS
    max_attachment_bytes: int = MAX_MESSAGE_ATTACHMENT_BYTES
    accepted_types: list[str]


class MessageThreadOut(BaseModel):
    """One page of the thread. Pages run from the newest back: the first page holds the latest messages and
    ``next_cursor`` fetches the older ones; within a page the messages are oldest first (newest last)."""

    engagement_id: UUID
    status: ThreadStatus
    opens_at_stage: EngagementState = Field(description="The stage the thread opens at (INTEREST_CONFIRMED)")
    can_post: bool = Field(description="The caller may post now (open, and not a viewer)")
    unread: int = Field(ge=0, description="Messages by others newer than the caller's read marker")
    last_read_at: datetime | None
    limits: ThreadLimits
    items: list[MessageOut]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the older page; null on the oldest")


class ReadOut(BaseModel):
    unread: int = Field(ge=0)
    last_read_at: datetime | None


class ReportOut(BaseModel):
    case_id: UUID
    created: bool = Field(description="False when the caller had already reported this message (the same case)")


class StagedAttachmentOut(BaseModel):
    """An upload waiting to be sent with the caller's next message (only the uploader sees it)."""

    id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    av_status: AvStatus


class AttachmentLinkOut(BaseModel):
    url: str = Field(description="A path on this API, signed for the caller, valid until expires_at")
    expires_at: datetime
