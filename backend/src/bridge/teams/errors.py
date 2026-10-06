"""The database's refusals as the teams API answers them (REQ-DEV-03; revision 0011's operating rules).

Every refusal that concerns another developer is the same 404 whatever its cause (a stranger, someone who turned Peers
off, a blocked developer, an unknown id), so nothing tells the cases apart; the codes below are what the web app keys
its own words on. Messages are [[COPY-REVIEW]].
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.exc import DBAPIError

from bridge.errors import ApiError, forbidden, not_found

NOT_A_PARTY: Final = "No invitation or thread of yours has this id."
PEER_UNAVAILABLE: Final = "You can invite developers from your peers list, or the ones you already team up with."
PROBLEM_UNAVAILABLE: Final = "Teams form on a published problem or a public, published Problem Brief."
ALREADY_INVITED: Final = "One of you already invited the other to team up on this problem."
ALREADY_DECIDED: Final = "This invitation was already answered, withdrawn or ended."
INVITATION_UNAVAILABLE: Final = "This invitation can no longer be accepted."
WRONG_PARTY: Final = "Only the invited developer accepts or declines; only the sender withdraws."
PEERS_OFF: Final = "Turn on Peers in your settings to team up."
THREAD_CLOSED: Final = "This thread is closed, so it is read-only."
NOT_A_COUNTERPART: Final = "Add a developer you have a team thread with."


def sqlstate(exc: DBAPIError) -> str | None:
    found = getattr(exc.orig, "sqlstate", None)
    return None if found is None else str(found)


def primary(exc: DBAPIError) -> str:
    """The error's primary message (the database's words, for telling refusals apart; never shown)."""
    return str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")


def constraint(exc: DBAPIError) -> str:
    return str(getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or "")


def peer_unavailable() -> ApiError:
    return ApiError(404, "peer_unavailable", PEER_UNAVAILABLE)


def problem_unavailable() -> ApiError:
    return ApiError(404, "problem_unavailable", PROBLEM_UNAVAILABLE)


def not_a_party() -> ApiError:
    return not_found(NOT_A_PARTY)


def thread_closed() -> ApiError:
    return ApiError(409, "thread_closed", THREAD_CLOSED)


def invitation_refusal(exc: DBAPIError) -> ApiError | None:
    """An invitation's INSERT refused: by ``team_invitations_open`` (P0002, a precise and uniform refusal), the pending
    pair's unique index (409), or the INSERT policy (any other 42501: 404, as for a stranger)."""
    state, message = sqlstate(exc), primary(exc)
    if state == "P0002":
        return problem_unavailable() if "no published problem" in message else peer_unavailable()
    if state == "23505" and constraint(exc) == "uq_team_invitations_pending_pair":
        return ApiError(409, "already_invited", ALREADY_INVITED)
    if state in ("42501", "23503"):
        return peer_unavailable()
    if state == "23514":
        return ApiError(422, "invalid_invitation", "Check the invitation's note and recipient.")
    return None


def decision_refusal(exc: DBAPIError) -> ApiError | None:
    """``app_decide_team_invitation``'s refusals: no invitation of the caller's (404), the wrong party (403), already
    decided (409), the sender or the problem no longer there (409)."""
    state, message = sqlstate(exc), primary(exc)
    if state == "42501":
        return not_a_party() if "no invitation of the caller" in message else forbidden("wrong_party", WRONG_PARTY)
    if state == "55000":
        if "already decided" in message:
            return ApiError(409, "already_decided", ALREADY_DECIDED)
        return ApiError(409, "invitation_unavailable", INVITATION_UNAVAILABLE)
    return None


def message_refusal(exc: DBAPIError) -> ApiError | None:
    """A team message's INSERT refused: a thread the caller does not read (404), a closed thread (409), the INSERT
    policy (a closed thread or a block in flight: 409)."""
    state, message = sqlstate(exc), primary(exc)
    if state == "42501":
        return not_a_party() if "no thread of the caller" in message else thread_closed()
    if state == "55000":
        return thread_closed()
    if state == "23514":
        return ApiError(422, "invalid_message", "A message has 1 to 4,000 characters and is not blank.")
    return None
