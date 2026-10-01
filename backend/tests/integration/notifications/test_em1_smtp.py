"""REQ-NOT-02 / REQ-NOT-01 end to end over SMTP: a Pitch's EM1, rendered from its templates, goes out through
``SmtpEmailProvider`` (Mailpit's adapter in dev and CI) to an in-process SMTP sink on loopback, and arrives as one
multipart/alternative message whose plain-text and HTML parts both carry the subject's facts, the receipt, the
timestamp state and the link to the proposal's own page, with no template syntax left unrendered (AC-SEC-5: loopback
only, nothing leaves the machine)."""

from __future__ import annotations

import asyncio
import email
import email.policy
import re
from email.message import EmailMessage as MimeMessage
from email.utils import parseaddr
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings
from bridge.notifications.email import SmtpEmailProvider
from tests.integration.proposals.helpers import Developers, ProposalWorld, rows, user_of
from tests.integration.proposals.pitch_helpers import PitchOrgs, pitch, pitchable
from tests.unit.notifications.test_smtp import SmtpStub

FRONTEND_APP = Path(__file__).resolve().parents[4] / "frontend" / "app"
TEMPLATE_SYNTAX = re.compile(r"\{\{|\}\}|\{%|%\}|\{#|#\}")


def part(message: MimeMessage, subtype: str) -> str:
    body = message.get_body((subtype,))
    assert isinstance(body, MimeMessage), f"no text/{subtype} part"
    content = body.get_content()
    assert isinstance(content, str)
    return content


async def test_em1_goes_out_over_smtp_with_both_parts_rendered_and_linking_to_the_proposal(
    developers: Developers, proposal_world: ProposalWorld, pitch_orgs: PitchOrgs, owner_engine: AsyncEngine
) -> None:
    dev, proposal_id = await pitchable(developers, proposal_world, title="Cold-chain alerts")
    settings: Settings = dev.app.state.settings  # type: ignore[attr-defined]
    sink = SmtpStub()
    server = await asyncio.start_server(sink.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        smtp = SmtpEmailProvider(host="127.0.0.1", port=port, sender=settings.email_from, timeout=10.0)
        dev.app.state.email_provider = smtp  # type: ignore[attr-defined]
        response = await pitch(dev, proposal_id, pitch_orgs.safaricom, pitch_orgs.telkom)
    assert response.status_code == 201, response.text
    assert response.json()["email_sent"] is True

    [me] = await rows(owner_engine, "SELECT email FROM users WHERE id = :u", u=user_of(dev))
    [receipt] = await rows(
        owner_engine,
        "SELECT v.cert_id FROM proposals p JOIN proposal_versions v ON v.id = p.current_version_id WHERE p.id = :p",
        p=proposal_id,
    )
    [raw] = sink.messages  # one message, to the developer only
    [(mail_from, rcpt_to)] = sink.envelopes
    assert mail_from.startswith(f"mail from:<{parseaddr(settings.email_from)[1]}>".lower().encode())
    assert rcpt_to == f"rcpt to:<{me.email}>".lower().encode()
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, MimeMessage)
    assert (message["To"], message["From"], message["X-Tags"]) == (me.email, settings.email_from, "em1")
    # Longer than 78 characters with its name, the header is folded as "Subject:" CRLF SP value (RFC 5322 2.2.3); mail
    # clients trim the blank that unfolding leaves, Python's parser keeps it.
    subject = str(message["Subject"]).strip()
    assert subject == 'Your proposal "Cold-chain alerts" is registered and sent to 1 organisation'
    assert message.get_content_type() == "multipart/alternative"
    text, html = part(message, "plain"), part(message, "html")

    base = settings.public_base_url.rstrip("/")
    link = f"{base}/dev/ideas/{proposal_id}"
    assert f"Open your proposal: {link}" in text
    assert html.count(f'href="{link}"') == 1
    assert re.findall(r'<a href="([^"]+)" data-cta="[^"]+"', html) == [link]  # the one call to action
    for page in ("(app)/dev/ideas/[id]", "(app)/settings/notifications", "(public)/help"):
        assert (FRONTEND_APP / page / "page.tsx").is_file(), page  # every link opens a page the web app has
    for path in ("/settings/notifications", "/help"):
        assert f"{base}{path}" in text
        assert f'href="{base}{path}"' in html

    for body in (text, html):
        assert "Cold-chain alerts" in body
        assert receipt.cert_id in body
        assert "Timestamp pending" in body  # the registration pipeline has not timestamped it yet
        assert pitch_orgs.safaricom.name in body
        assert f"{pitch_orgs.telkom.name} isn" in body  # saved for (held): "isn't on the platform yet", escaped in HTML
        assert "on the platform yet. Your proposal is saved" in body
        assert "Nairobi, Kenya" in body
    for rendered in (subject, text, html):
        assert not TEMPLATE_SYNTAX.search(rendered), TEMPLATE_SYNTAX.findall(rendered)
        assert "None" not in rendered
    assert "<" not in text  # the plain-text part is text, not markup
    assert html.lstrip().startswith("<!DOCTYPE html>")

    [delivery] = await rows(
        owner_engine,
        "SELECT kind, status, provider, provider_message_id FROM notification_deliveries WHERE user_id = :u",
        u=user_of(dev),
    )
    assert tuple(delivery) == ("em1", "sent", "smtp", message["Message-ID"].strip("<>"))
