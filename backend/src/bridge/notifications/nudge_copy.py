"""The fixed words of P28's tracker notices, in English and Kiswahili (REQ-NOT-05, REQ-NOT-03, REQ-ENG-06; docs/spec/06
6.10 EM5 and EM6; ``REQUIREMENTS.md`` §5 N05, N07, N12).

What the nudge job (``bridge.engagements.nudges``) and the procurement route's notice say: the organisation's
escalations (first contact late, the procurement route waiting, a milestone review late), EM6 Contact overdue (the
organisation's and the developer's versions), EM5 Signature needed (the NDA reminders, each party's version), the
milestone review reminder (in-app only, N12) and the developer's notice of a chosen procurement route (N05). Each is a
title and a body for the bell, and a subject and paragraphs for the email (``render``: ``templates/nudge.*.j2``, one
call to action, the engagement's ref in the footer).

Plain code fills every value: a proposal's title and an organisation's name (people's words) are made unlinkable
(``em1.unlinkable``: one line, no dot or at sign a mail client turns into a link, no scheme) and quoted in fixed copy;
the HTML part autoescapes them; dates, counts and routes are the job's. No organisation's free text (a justification,
a note) is ever in a notice: the tracker shows it. No statute is cited. A person reads their notices in their own
language (``users.locale``: ``sw`` is Kiswahili, anything else English). Nothing here is worded by an LLM.
[[COPY-REVIEW]] all the copy below; [[SW-REVIEW]] the Kiswahili, a draft for a fluent reviewer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.models.enums import ProcurementRoute
from bridge.notifications.em1 import unlinkable

Locale = Literal["en", "sw"]
LOCALES: Final[tuple[Locale, ...]] = ("en", "sw")
_MONTHS_SW: Final = (
    "Januari",
    "Februari",
    "Machi",
    "Aprili",
    "Mei",
    "Juni",
    "Julai",
    "Agosti",
    "Septemba",
    "Oktoba",
    "Novemba",
    "Desemba",
)
# The email's fixed frame in each language: the call to action and the footer's words.
CHROME: Final[Mapping[Locale, Mapping[str, str]]] = {
    "en": {
        "cta": "Open your tracker",
        "manage": "Manage notifications",
        "help": "Help",
        "place": "Nairobi, Kenya",
        "ref": "Engagement ref",
        "or_open": "Or open this address",
    },
    "sw": {
        "cta": "Fungua kifuatiliaji chako",
        "manage": "Dhibiti arifa",
        "help": "Msaada",
        "place": "Nairobi, Kenya",
        "ref": "Kumbukumbu ya ushirikiano",
        "or_open": "Au fungua anwani hii",
    },
}
# How a public entity will buy (docs/spec/06 6.9 stage 3b), as a notice names it.
ROUTES: Final[Mapping[Locale, Mapping[ProcurementRoute, str]]] = {
    "en": {
        ProcurementRoute.DIRECT: "direct procurement",
        ProcurementRoute.RFQ_TENDER: "a request for quotation or tender",
        ProcurementRoute.PPP_PIP: "a privately-initiated PPP proposal",
        ProcurementRoute.INNOVATION_CHALLENGE: "an innovation challenge or grant",
        ProcurementRoute.PILOT_MOU: "a pilot under a memorandum of understanding",
    },
    "sw": {
        ProcurementRoute.DIRECT: "ununuzi wa moja kwa moja",
        ProcurementRoute.RFQ_TENDER: "ombi la bei au zabuni",
        ProcurementRoute.PPP_PIP: "pendekezo la PPP lililoanzishwa na sekta binafsi",
        ProcurementRoute.INNOVATION_CHALLENGE: "shindano la ubunifu au ruzuku",
        ProcurementRoute.PILOT_MOU: "majaribio chini ya mkataba wa maelewano (MoU)",
    },
}


class Copy(NamedTuple):
    """One notice's fixed words in one language: ``{org}``, ``{title}``, ``{date}``, ``{days}``, ``{expires}``,
    ``{route}`` and ``{seq}`` are filled in."""

    title: str  # the bell's title
    body: str  # the bell's text
    subject: str  # the email's subject ("" for an in-app-only notice)
    paragraphs: tuple[str, ...]  # the email's text


# The notices, by name and language. The email of an in-app-only notice (the milestone review reminder) is empty.
COPY: Final[Mapping[str, Mapping[Locale, Copy]]] = {
    # N05, the developer: the organisation chose its procurement route (3b); EM2 goes with it.
    "route_chosen": {
        "en": Copy(
            "Procurement route chosen",
            '{org} chose how it will buy "{title}": {route}. Its contact will reach you by {date}.',
            'Procurement route chosen: "{title}"',
            (
                '{org} chose how it will buy "{title}": {route}.',
                "Its named contact will reach you by {date}. The route and the reason given are on your tracker.",
            ),
        ),
        "sw": Copy(
            "Njia ya ununuzi imechaguliwa",
            '{org} imechagua jinsi itakavyonunua "{title}": {route}. Mhusika wake atawasiliana nawe kufikia {date}.',
            'Njia ya ununuzi imechaguliwa: "{title}"',
            (
                '{org} imechagua jinsi itakavyonunua "{title}": {route}.',
                "Mhusika wake aliyetajwa atawasiliana nawe kufikia {date}. Njia hiyo na sababu iliyotolewa ziko kwenye"
                " kifuatiliaji chako.",
            ),
        ),
    },
    # N05, the organisation's admins and escalation contact: first contact not marked escalate_bd after stage 3.
    "contact_escalation": {
        "en": Copy(
            "First contact is late",
            'First contact on "{title}" has not been marked {days} business days after it was approved to proceed'
            " (non-binding). The contact-by date is {date}.",
            'Escalation: first contact on "{title}" is late',
            (
                'First contact with the developer on "{title}" has not been marked {days} business days after {org}'
                " approved it to proceed (non-binding).",
                "The contact-by date is {date}. You are told as an admin or the escalation contact of {org}: check"
                " that the named contact reaches the developer and marks first contact on the tracker.",
            ),
        ),
        "sw": Copy(
            "Mawasiliano ya kwanza yamechelewa",
            'Mawasiliano ya kwanza kuhusu "{title}" hayajawekwa siku {days} za kazi baada ya kuidhinishwa kuendelea'
            " (haifungi kisheria). Tarehe ya kuwasiliana ni {date}.",
            'Kwa wasimamizi: mawasiliano ya kwanza kuhusu "{title}" yamechelewa',
            (
                'Mawasiliano ya kwanza na msanidi programu kuhusu "{title}" hayajawekwa siku {days} za kazi baada ya'
                " {org} kuidhinisha kuendelea (haifungi kisheria).",
                "Tarehe ya kuwasiliana ni {date}. Unaarifiwa kama msimamizi au mhusika wa masuala yaliyochelewa wa"
                " {org}: hakikisha mhusika aliyetajwa anawasiliana na msanidi programu na kuweka mawasiliano ya kwanza"
                " kwenye kifuatiliaji.",
            ),
        ),
    },
    # EM6 Contact overdue, the organisation's version (its named contact and its admins).
    "contact_overdue_org": {
        "en": Copy(
            "Contact overdue",
            'The contact-by date for "{title}" was {date} and first contact has not been marked. Reach the developer'
            " and mark first contact on the tracker.",
            'Contact overdue: "{title}"',
            (
                'The contact-by date for "{title}" was {date}, and first contact with the developer has not been'
                " marked.",
                "Reach the developer now and mark first contact on the tracker. If first contact is not made, the"
                " engagement expires on {expires}.",
            ),
        ),
        "sw": Copy(
            "Mawasiliano yamechelewa",
            'Tarehe ya kuwasiliana kuhusu "{title}" ilikuwa {date} na mawasiliano ya kwanza hayajawekwa. Wasiliana na'
            " msanidi programu na uweke mawasiliano ya kwanza kwenye kifuatiliaji.",
            'Mawasiliano yamechelewa: "{title}"',
            (
                'Tarehe ya kuwasiliana kuhusu "{title}" ilikuwa {date}, na mawasiliano ya kwanza na msanidi programu'
                " hayajawekwa.",
                "Wasiliana na msanidi programu sasa na uweke mawasiliano ya kwanza kwenye kifuatiliaji. Mawasiliano ya"
                " kwanza yasipofanyika, muda wa ushirikiano utaisha tarehe {expires}.",
            ),
        ),
    },
    # EM6 Contact overdue, the developer's version.
    "contact_overdue_developer": {
        "en": Copy(
            "Contact overdue",
            '{org} said its contact would reach you about "{title}" by {date}, and has not marked first contact. We'
            " have reminded {org}.",
            'Contact overdue: "{title}"',
            (
                '{org} said its contact would reach you about "{title}" by {date}, and has not marked first contact'
                " yet. We have reminded {org}.",
                "You can write to them in the engagement's messages on your tracker. If first contact is not made, the"
                " engagement expires on {expires}.",
            ),
        ),
        "sw": Copy(
            "Mawasiliano yamechelewa",
            '{org} ilisema mhusika wake atawasiliana nawe kuhusu "{title}" kufikia {date}, na haijaweka mawasiliano'
            " ya kwanza. Tumeikumbusha {org}.",
            'Mawasiliano yamechelewa: "{title}"',
            (
                '{org} ilisema mhusika wake atawasiliana nawe kuhusu "{title}" kufikia {date}, na bado haijaweka'
                " mawasiliano ya kwanza. Tumeikumbusha {org}.",
                "Unaweza kuwaandikia kwenye ujumbe wa ushirikiano katika kifuatiliaji chako. Mawasiliano ya kwanza"
                " yasipofanyika, muda wa ushirikiano utaisha tarehe {expires}.",
            ),
        ),
    },
    # EM5 Signature needed: the mutual NDA reminder, the developer's version.
    "nda_reminder_developer": {
        "en": Copy(
            "Signature needed",
            'The mutual NDA for "{title}" is waiting for your signature. It is due by {date}.',
            'Signature needed: the mutual NDA for "{title}"',
            (
                'The mutual NDA for "{title}" with {org} is waiting for your signature.',
                "It is due by {date}. Open your tracker to read it and sign.",
            ),
        ),
        "sw": Copy(
            "Sahihi inahitajika",
            'NDA ya pande zote ya "{title}" inasubiri sahihi yako. Mwisho wake ni {date}.',
            'Sahihi inahitajika: NDA ya pande zote ya "{title}"',
            (
                'NDA ya pande zote ya "{title}" na {org} inasubiri sahihi yako.',
                "Mwisho wake ni {date}. Fungua kifuatiliaji chako uisome na kuitia sahihi.",
            ),
        ),
    },
    # EM5 Signature needed: the mutual NDA reminder, the organisation's signatories.
    "nda_reminder_org": {
        "en": Copy(
            "Signature needed",
            'The mutual NDA for "{title}" is waiting for your organisation\'s signature. It is due by {date}.',
            'Signature needed: the mutual NDA for "{title}"',
            (
                'The mutual NDA for "{title}" is waiting for the signature of {org}. As its signatory, you can sign'
                " it.",
                "It is due by {date}. Open the tracker to read it and sign.",
            ),
        ),
        "sw": Copy(
            "Sahihi inahitajika",
            'NDA ya pande zote ya "{title}" inasubiri sahihi ya shirika lako. Mwisho wake ni {date}.',
            'Sahihi inahitajika: NDA ya pande zote ya "{title}"',
            (
                'NDA ya pande zote ya "{title}" inasubiri sahihi ya {org}. Kama mtia sahihi wake, unaweza kuitia'
                " sahihi.",
                "Mwisho wake ni {date}. Fungua kifuatiliaji uisome na kuitia sahihi.",
            ),
        ),
    },
    # N05, the organisation's admins and escalation contact: its procurement route undecided escalate_bd after 3b.
    "procurement_escalation": {
        "en": Copy(
            "Procurement route waiting",
            '"{title}" has waited {days} business days for {org} to choose its procurement route. It is due by {date}.',
            'Escalation: choose the procurement route for "{title}"',
            (
                '"{title}" was approved to proceed (non-binding) and has waited {days} business days for {org} to'
                " choose how it will buy.",
                "An owner or admin chooses the procurement route on the tracker; it is due by {date}. You are told as"
                " an admin or the escalation contact of {org}.",
            ),
        ),
        "sw": Copy(
            "Njia ya ununuzi inasubiriwa",
            '"{title}" imesubiri siku {days} za kazi {org} ichague njia yake ya ununuzi. Mwisho wake ni {date}.',
            'Kwa wasimamizi: chagueni njia ya ununuzi ya "{title}"',
            (
                '"{title}" iliidhinishwa kuendelea (haifungi kisheria) na imesubiri siku {days} za kazi {org} ichague'
                " jinsi itakavyonunua.",
                "Mmiliki au msimamizi huchagua njia ya ununuzi kwenye kifuatiliaji; mwisho wake ni {date}. Unaarifiwa"
                " kama msimamizi au mhusika wa masuala yaliyochelewa wa {org}.",
            ),
        ),
    },
    # N12, the organisation's reviewers of the engagement: a submitted milestone unreviewed reminder_bd (in-app only).
    "milestone_reminder": {
        "en": Copy(
            "Milestone review due",
            'Milestone {seq} of "{title}" has waited {days} business days for your review. Accept it or ask for'
            " changes on the tracker.",
            "",
            (),
        ),
        "sw": Copy(
            "Tathmini ya hatua inasubiriwa",
            'Hatua {seq} ya "{title}" imesubiri tathmini yenu siku {days} za kazi. Ikubalini au ombeni mabadiliko'
            " kwenye kifuatiliaji.",
            "",
            (),
        ),
    },
    # N12, the organisation's admins and escalation contact: the milestone still unreviewed escalation_bd.
    "milestone_escalation": {
        "en": Copy(
            "Milestone review late",
            'Milestone {seq} of "{title}" has waited {days} business days for review.',
            'Escalation: milestone {seq} of "{title}" awaits review',
            (
                'Milestone {seq} of "{title}" was submitted for review {days} business days ago and has not been'
                " accepted or sent back for changes.",
                "You are told as an admin or the escalation contact of {org}: check that a reviewer decides it on the"
                " tracker.",
            ),
        ),
        "sw": Copy(
            "Tathmini ya hatua imechelewa",
            'Hatua {seq} ya "{title}" imesubiri tathmini siku {days} za kazi.',
            'Kwa wasimamizi: hatua {seq} ya "{title}" inasubiri tathmini',
            (
                'Hatua {seq} ya "{title}" iliwasilishwa kwa tathmini siku {days} za kazi zilizopita na haijakubaliwa'
                " wala kurudishwa kwa mabadiliko.",
                "Unaarifiwa kama msimamizi au mhusika wa masuala yaliyochelewa wa {org}: hakikisha mkaguzi anaiamua"
                " kwenye kifuatiliaji.",
            ),
        ),
    },
}


def locale_of(value: str | None) -> Locale:
    """The language a person reads: Kiswahili for ``sw``, English for anything else."""
    return "sw" if value == "sw" else "en"


def date_text(day: date, locale: Locale) -> str:
    """``20 Oct 2026`` in English (the tracker's dates), ``20 Oktoba 2026`` in Kiswahili."""
    if locale == "sw":
        return f"{day.day} {_MONTHS_SW[day.month - 1]} {day.year}"
    return f"{day.day} {day:%b %Y}"


@dataclass(frozen=True, slots=True)
class Values:
    """What a notice says about its engagement (plain code's values; ``org`` and ``title`` are people's words)."""

    org: str
    title: str
    on: date | None = None  # {date}: the contact-by or due date
    days: int | None = None  # {days}: business days waited
    expires: date | None = None  # {expires}: the day the engagement expires if nothing happens
    route: ProcurementRoute | None = None  # {route}
    seq: int | None = None  # {seq}: the milestone's number


class Wording(NamedTuple):
    title: str
    body: str
    subject: str
    paragraphs: tuple[str, ...]


def wording(name: str, locale: Locale, values: Values) -> Wording:
    """The notice ``name`` in ``locale``, its values filled in: names and titles unlinkable, dates in the language."""
    copy = COPY[name][locale]
    fields = {
        "org": unlinkable(values.org),
        "title": unlinkable(values.title),
        "date": date_text(values.on, locale) if values.on is not None else "",
        "days": "" if values.days is None else str(values.days),
        "expires": date_text(values.expires, locale) if values.expires is not None else "",
        "route": ROUTES[locale][values.route] if values.route is not None else "",
        "seq": "" if values.seq is None else str(values.seq),
    }
    return Wording(
        title=copy.title.format(**fields),
        body=copy.body.format(**fields),
        subject=copy.subject.format(**fields),
        paragraphs=tuple(paragraph.format(**fields) for paragraph in copy.paragraphs),
    )


class Rendered(NamedTuple):
    subject: str
    text: str
    html: str


_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(words: Wording, locale: Locale, *, engagement_id: UUID, path: str, base_url: str, product: str) -> Rendered:
    """The email of a notice: its subject, its paragraphs, one call to action to the recipient's tracker (a platform
    path only), and the footer with the engagement's ref, in the recipient's language. Fixed templates
    (``templates/nudge.*.j2``); the HTML part autoescapes."""
    if not words.subject or not words.paragraphs:
        raise ValueError("this notice has no email")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("a notice links to a platform path")
    base = base_url.rstrip("/")
    chrome = CHROME[locale]
    values = {
        "lang": locale,
        "subject": words.subject,
        "paragraphs": list(words.paragraphs),
        "button_label": chrome["cta"],
        "button_url": base + path,
        "or_open": chrome["or_open"],
        "settings_url": f"{base}/settings/notifications",
        "help_url": f"{base}/help",
        "manage_label": chrome["manage"],
        "help_label": chrome["help"],
        "place": chrome["place"],
        "ref_label": chrome["ref"],
        "engagement_ref": str(engagement_id),
        "product": unlinkable(product),
    }
    return Rendered(
        words.subject,
        _ENV.get_template("nudge.txt.j2").render(values),
        _ENV.get_template("nudge.html.j2").render(values),
    )
