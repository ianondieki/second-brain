import { useLocale, useTranslations } from "next-intl";
import type { ComponentType } from "react";

import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { titleLinkClass } from "@/components/ui/Button";
import { Section } from "@/components/ui/Section";
import { PauseIcon, PlayIcon } from "@/components/icons/lucide";
import { PencilIcon, SparkIcon } from "@/components/ui/icons";
import { AlertIcon, CheckIcon, ClockIcon, LockIcon } from "@/components/ui/status-icons";

import { MessageIcon } from "./icons";

import { formatDate, notesByEvent, type Command, type History, type HistoryEvent, type Note } from "./model";
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
 * the answer, a hold's reason and date: the engagement's `notes`), as plain text. The thread's messages are entries
 * too ("Message from …", the side and the time; never the text, which stays on the Messages tab; REQ-ENG-11).
 */
export function HistoryList({
  history,
  notes = [],
  messageLink,
}: {
  history: History;
  notes?: readonly Note[];
  /** Where a message's entry links: that message in the thread (the Messages route, "#message-<id>"). */
  messageLink?: (messageId: string) => string;
}) {
  const t = useTranslations("tracker");
  const locale = useLocale();
  const entries = timeline(history);
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
      {/* A timeline, newest first: a rail down the left with a mark per event (the latest in bloom), the event's
          name, who acted, when, and any words they wrote. */}
      <ol className="relative flex flex-col">
        {entries.map((entry, i) => {
          const rail =
            i < entries.length - 1 ? (
              <span aria-hidden="true" className="absolute top-8 bottom-0 left-[13px] w-0.5 rounded-full bg-ink-soft/25" />
            ) : null;
          // A mark per event with its icon (P25): the latest filled in bloom; messages in bloom; an end in the error tone.
          const kind = entry.kind === "message" ? "message" : eventKind(entry.event.command);
          const { Icon, tone } = MARKS[kind];
          const mark = (
            <span aria-hidden="true" className="event-mark" data-latest={i === 0 ? "" : undefined} data-tone={tone} data-mark-kind={kind}>
              <Icon />
            </span>
          );
          if (entry.kind === "message") {
            const message = entry.message;
            return (
              <li key={`message-${message.id}`} data-history-message={message.sender_party} className="relative flex gap-4 pb-7 last:pb-0">
                {rail}
                {mark}
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold [overflow-wrap:anywhere] text-ink">
                    {messageLink ? (
                      <Link href={messageLink(message.id)} className={`${titleLinkClass} -my-2.5 inline-block py-2.5`}>
                        {t("history.message", { name: message.sender_name })}
                      </Link>
                    ) : (
                      t("history.message", { name: message.sender_name })
                    )}
                  </h3>
                  <p className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-soft">
                    <span className="text-ink">{t(`history.messageSide.${message.sender_party}`)}</span>
                    <Eat iso={message.created_at} />
                  </p>
                </div>
              </li>
            );
          }
          const event = entry.event;
          return (
            <li key={event.id} data-event={event.command} className="relative flex gap-4 pb-7 last:pb-0">
              {rail}
              {mark}
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-ink">
                  {EVENT_KEYS.has(event.command) ? t(`event.${event.command as Command | "create" | "expire"}`) : t("event.other")}
                </h3>
                <p className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-soft">
                  <span className="text-ink">
                    {t("history.actor", {
                      name: event.actor_name ?? t("endorsements.platform"),
                      role: t(`role.${event.actor_role}`),
                    })}
                  </span>
                  <Eat iso={event.created_at} />
                </p>
                <NoteText note={noteOf.get(event.id)} locale={locale} />
              </div>
            </li>
          );
        })}
      </ol>
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

type HistoryMessage = NonNullable<History["messages"]>[number];
type Entry = { kind: "event"; at: number; event: HistoryEvent } | { kind: "message"; at: number; message: HistoryMessage };

/**
 * The events (newest first, by their sequence) and the thread's messages in one timeline, newest first by time. The
 * sort is stable, so events of the same moment keep their order.
 */
export function timeline(history: Pick<History, "events" | "messages">): Entry[] {
  const events: Entry[] = [...history.events]
    .sort((a, b) => b.seq - a.seq)
    .map((event) => ({ kind: "event", at: Date.parse(event.created_at), event }));
  const messages: Entry[] = (history.messages ?? []).map((message) => ({
    kind: "message",
    at: Date.parse(message.created_at),
    message,
  }));
  return [...events, ...messages].sort((a, b) => b.at - a.at);
}

type MarkKind = "start" | "message" | "sign" | "pause" | "resume" | "end" | "nda" | "time" | "step";
const MARKS: Record<MarkKind, { Icon: ComponentType<{ className?: string }>; tone?: "message" | "end" }> = {
  start: { Icon: SparkIcon },
  message: { Icon: MessageIcon, tone: "message" },
  sign: { Icon: PencilIcon },
  pause: { Icon: PauseIcon },
  resume: { Icon: PlayIcon },
  end: { Icon: AlertIcon, tone: "end" },
  nda: { Icon: LockIcon },
  time: { Icon: ClockIcon, tone: "end" },
  step: { Icon: CheckIcon },
};

/** The icon family of an event: how it started, a signature or terms, a pause, a resumption, an end, the NDA, a step. */
export function eventKind(command: string): MarkKind {
  if (command === "create") return "start";
  if (command === "expire") return "time";
  if (["decline", "decline_interest", "withdraw", "cancel_request"].includes(command)) return "end";
  if (["pause", "request_info"].includes(command)) return "pause";
  if (["resume", "answer_info", "reopen_negotiation"].includes(command)) return "resume";
  if (["send_nda", "sign_nda"].includes(command)) return "nda";
  if (command.startsWith("sign_") || ["propose_terms", "mark_final"].includes(command)) return "sign";
  return "step";
}
