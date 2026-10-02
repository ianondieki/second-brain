import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";

import { formatDate, notesByEvent, type Command, type History, type Note } from "./model";
import { Eat } from "./When";

/** The event names the History tab words: every command, plus the genesis ("create") and the system's expiry. */
const EVENT_KEYS = new Set<string>([
  "create",
  "accept_interest",
  "decline_interest",
  "start_review",
  "decline",
  "approve",
  "withdraw",
  "mark_contacted",
  "confirm_contact",
  "send_nda",
  "sign_nda",
  "propose_terms",
  "mark_final",
  "reopen_negotiation",
  "sign_agreement",
  "start_milestone",
  "submit_milestone",
  "accept_milestone",
  "request_changes",
  "deliver",
  "accept_delivery",
  "sign_certificate",
  "record_payment",
  "confirm_payment",
  "request_info",
  "answer_info",
  "cancel_request",
  "pause",
  "resume",
  "expire",
] satisfies Array<Command | "create" | "expire">);

/**
 * The History tab (REQ-ENG-02; docs/spec/06 6.9 Persistence): the engagement's events in order, each with its time
 * in EAT, who acted in which role, and what happened. Both parties see the same list (AC-TRACK-3). The line above it
 * says whether the hash chain checked out when the API read it. A side state's event carries its text (the question,
 * the answer, a hold's reason and date: the engagement's `notes`), as plain text.
 */
export function HistoryList({ history, notes = [] }: { history: History; notes?: readonly Note[] }) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  const events = [...history.events].sort((a, b) => b.seq - a.seq);
  const noteOf = notesByEvent(history.events, notes);
  return (
    <Section
      title={t("history.title")}
      headingId="history-heading"
      description={
        <Badge
          data-chain={history.chain_verified ? "verified" : "unverified"}
          tone={history.chain_verified ? "ok" : "error"}
          icon={history.chain_verified ? <CheckIcon /> : <AlertIcon />}
        >
          {history.chain_verified ? t("history.chainOk") : t("history.chainBroken")}
        </Badge>
      }
    >
      <RowList ordered>
        {events.map((event) => (
          <Row
            key={event.id}
            data-event={event.command}
            title={EVENT_KEYS.has(event.command) ? t(`event.${event.command as Command | "create" | "expire"}`) : t("event.other")}
            meta={t("history.actor", {
              name: event.actor_name ?? t("endorsements.platform"),
              role: t(`role.${event.actor_role}`),
            })}
          >
            <p className="text-sm text-ink-soft">
              <Eat iso={event.created_at} />
            </p>
            <NoteText note={noteOf.get(event.id)} locale={locale} />
          </Row>
        ))}
      </RowList>
    </Section>
  );
}

/** An event's text: its kind as a small label (a hold's with the resume date), then the words as written. */
function NoteText({ note, locale }: { note: Note | undefined; locale: string }) {
  const t = useTranslations("tracker");
  if (!note) return null;
  return (
    <div data-note={note.kind} className="mt-2 border-l-2 border-line pl-3">
      <p className="text-sm font-semibold text-ink-soft">
        {note.kind === "hold"
          ? t("history.note.hold", { date: note.resume_at ? formatDate(note.resume_at, locale) : "" })
          : t(`history.note.${note.kind}`)}
      </p>
      <p className="whitespace-pre-line text-ink [overflow-wrap:anywhere]">{note.body}</p>
    </div>
  );
}
