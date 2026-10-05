"use client";

import { useRouter } from "next/navigation";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon } from "@/components/ui/status-icons";
import { useHydrated } from "@/lib/hooks/useHydrated";

import * as defaultCalls from "./calls";
import type { ThreadCalls } from "./calls";
import { Composer } from "./Composer";
import { FileIcon } from "./FileIcon";
import {
  fileSize,
  firstUnread,
  groupByDay,
  messageTime,
  prependOlder,
  type Message,
  type Thread as ThreadPage,
} from "./thread";

export type { ThreadCalls };

// The report sheet loads on the first press of a Report (docs/spec/07 item 5: the route sits near its 150 KB).
const ReportSheet = lazy(() => import("./ReportSheet").then((m) => ({ default: m.ReportSheet })));

export interface ThreadProps {
  engagementId: string;
  /** The thread's first page (the latest messages), as the server read it. */
  initial: ThreadPage;
  /** Today in Nairobi on the platform's clock (the tracker's `today`), for "Today" and "Yesterday". */
  today: string;
  locale: string;
  /** The organisation's name: what an organisation member's message says beside the sender. */
  orgName: string;
  /** The sentence of an empty thread (formatted on the server: it differs by who reads it), or null for none. */
  empty: string | null;
  /** Tests pass fakes; the real calls otherwise. */
  calls?: Partial<ThreadCalls>;
}

/**
 * The engagement's thread (REQ-ENG-11; docs/spec/06 6.9 "Messages tab"): the messages by day, oldest first, each with
 * its sender, side and time, its text exactly as typed (never markup, never a link) and its files; earlier pages on
 * request; a Report on everyone else's messages; the composer when the caller may post. Opening it marks the thread
 * read up to its newest message.
 */
export function Thread({ engagementId, initial, today, locale, orgName, empty, calls }: ThreadProps) {
  const t = useStrings("trackerMessages");
  const router = useRouter();
  const hydrated = useHydrated();
  const call: ThreadCalls = useMemo(() => ({ ...defaultCalls, ...calls }), [calls]);
  const [messages, setMessages] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [earlier, setEarlier] = useState<"idle" | "busy" | "failed">("idle");
  const [newFrom] = useState(() => firstUnread(initial.items, initial.last_read_at));
  const [reported, setReported] = useState<Record<string, "reported" | "reportedAgain">>({});
  const [focusId, setFocusId] = useState<string | null>(null);
  const [reportTarget, setReportTarget] = useState<{ message: Message } | null>(null);

  // Seen: the read marker moves up to the newest message shown (once; a refusal changes nothing on the page).
  const marked = useRef(false);
  useEffect(() => {
    const last = initial.items.at(-1);
    if (marked.current || initial.unread === 0 || !last) return;
    marked.current = true;
    void call.markRead(engagementId, last.id);
  }, [call, engagementId, initial]);

  useEffect(() => {
    if (focusId) document.getElementById(focusId)?.focus();
  }, [focusId]);

  async function loadEarlier() {
    if (!cursor || earlier === "busy") return;
    setEarlier("busy");
    const outcome = await call.olderPage(engagementId, cursor);
    if (!outcome.ok) {
      setEarlier("failed");
      return;
    }
    setMessages((shown) => prependOlder(shown, outcome.thread.items));
    setCursor(outcome.thread.next_cursor);
    setEarlier("idle");
    // Reading goes on from the oldest message just loaded.
    const first = outcome.thread.items[0];
    if (first) setFocusId(`message-${first.id}`);
  }

  const groups = groupByDay(messages, today, locale);
  return (
    <div className="flex flex-col gap-6" data-thread="" data-hydrated={hydrated ? "true" : "false"}>
      {cursor ? (
        <div className="flex flex-col items-center gap-2">
          <Button variant="secondary" busy={earlier === "busy"} onClick={() => void loadEarlier()} data-load-earlier="">
            {earlier === "busy" ? t("loadingEarlier") : t("loadEarlier")}
          </Button>
          {earlier === "failed" ? <Alert className="w-full">{t("earlierFailed")}</Alert> : null}
        </div>
      ) : null}

      {groups.length === 0 ? (
        empty === null ? null : <p className="text-ink-soft" data-thread-empty="">
          {empty}
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.day} aria-labelledby={`day-${group.day}`} className="flex flex-col gap-5" data-day={group.day}>
            <h3 id={`day-${group.day}`} className="flex items-center gap-3 text-xs font-semibold text-ink-soft">
              <span aria-hidden="true" className="h-px flex-1 bg-line" />
              {group.label ? t(group.label) : group.date}
              <span aria-hidden="true" className="h-px flex-1 bg-line" />
            </h3>
            <ol className="flex flex-col gap-5">
              {group.messages.map((message) => (
                <li key={message.id} className="flex flex-col gap-5">
                  {message.id === newFrom ? (
                    <p data-new-divider="" className="flex items-center gap-3 text-xs font-bold text-accent">
                      {t("newDivider")}
                      <span aria-hidden="true" className="h-0.5 flex-1 rounded-full bg-accent" />
                    </p>
                  ) : null}
                  <MessageItem
                    message={message}
                    engagementId={engagementId}
                    locale={locale}
                    orgName={orgName}
                    reported={reported[message.id]}
                    onReport={() => {
                      setReportTarget({ message });
                    }}
                    calls={call}
                  />
                </li>
              ))}
            </ol>
          </section>
        ))
      )}

      {reportTarget ? (
        <Suspense fallback={null}>
          <ReportSheet
            engagementId={engagementId}
            target={reportTarget}
            calls={call}
            onReported={(message, created) => setReported((now) => ({ ...now, [message.id]: created ? "reported" : "reportedAgain" }))}
          />
        </Suspense>
      ) : null}

      {initial.can_post ? (
        <Composer
          engagementId={engagementId}
          limits={initial.limits}
          locale={locale}
          calls={call}
          onSent={(message) => setMessages((shown) => [...shown, message])}
          onClosed={() => router.refresh()}
        />
      ) : null}
    </div>
  );
}

function MessageItem({
  message,
  engagementId,
  locale,
  orgName,
  reported,
  onReport,
  calls,
}: {
  message: Message;
  engagementId: string;
  locale: string;
  orgName: string;
  reported?: "reported" | "reportedAgain";
  onReport: () => void;
  calls: ThreadCalls;
}) {
  const t = useStrings("trackerMessages");
  const headId = `message-${message.id}-from`;
  const mine = message.mine;
  return (
    // Own messages sit to the right on a petal surface and are headed "You": the side is never said by colour alone.
    <article
      id={`message-${message.id}`}
      tabIndex={-1}
      aria-labelledby={headId}
      data-message={message.id}
      data-mine={mine ? "true" : "false"}
      className={cn("flex scroll-mt-6 gap-3 focus:outline-none", mine ? "ml-8 justify-end sm:ml-24" : "mr-8 sm:mr-24")}
    >
      {mine ? null : <Avatar name={message.sender_name} kind={message.sender_party === "org" ? "org" : "person"} size="sm" className="mt-0.5" />}
      <div className={cn("flex min-w-0 flex-col gap-1.5", mine && "items-end")}>
        <p id={headId} className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="font-semibold text-ink">{mine ? t("you") : message.sender_name}</span>
          {mine ? null : (
            <span className="text-ink-soft">{message.sender_party === "developer" ? t("developer") : orgName}</span>
          )}
          <time dateTime={message.created_at} className="text-ink-soft tabular-nums">
            {messageTime(message.created_at, locale)}
          </time>
        </p>
        <div
          data-body=""
          className={cn(
            "max-w-full rounded-panel border px-4 py-3 whitespace-pre-wrap [overflow-wrap:anywhere]",
            mine ? "rounded-tr-md border-accent-line bg-accent-wash text-ink" : "rounded-tl-md border-line bg-field text-ink",
            message.redacted && "text-ink-soft italic",
          )}
        >
          {message.redacted ? t("redacted") : message.body}
        </div>
        {message.attachments.length > 0 ? (
          <ul aria-label={t("files")} className="flex w-full flex-col gap-2">
            {message.attachments.map((file) => (
              <SentFileRow key={file.id} engagementId={engagementId} messageId={message.id} file={file} locale={locale} calls={calls} />
            ))}
          </ul>
        ) : null}
        {mine || message.redacted ? null : (
          <ReportControl reported={reported} onOpen={onReport} describedBy={headId} />
        )}
      </div>
    </article>
  );
}

/** A sent file: its name, size and status (sent files are always scanned and clean), and the way to open it. */
function SentFileRow({
  engagementId,
  messageId,
  file,
  locale,
  calls,
}: {
  engagementId: string;
  messageId: string;
  file: Message["attachments"][number];
  locale: string;
  calls: ThreadCalls;
}) {
  const t = useStrings("trackerMessages");
  const [problem, setProblem] = useState<"downloadFailed" | "downloadChanged" | null>(null);
  const [busy, setBusy] = useState(false);

  async function open() {
    setBusy(true);
    setProblem(null);
    const link = await calls.fileLink(engagementId, messageId, file.id);
    setBusy(false);
    if (link.ok) window.location.assign(link.url);
    else setProblem(link.changed ? "downloadChanged" : "downloadFailed");
  }

  return (
    <li data-file={file.id} className="flex flex-col gap-1">
      <div className="flex min-h-11 items-center gap-3 rounded-control border border-line bg-field py-1 pr-1 pl-3">
        <FileIcon className="size-5 shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-ink">{file.file_name}</span>
          <span className="flex flex-wrap gap-x-3 text-xs text-ink-soft tabular-nums">
            <span>{fileSize(file.size_bytes, locale)}</span>
            <span className="inline-flex items-center gap-1 text-ok" data-file-status="ready">
              <CheckIcon className="size-3.5" />
              {t("status.ready")}
            </span>
          </span>
        </span>
        <Button variant="link" busy={busy} onClick={() => void open()} aria-describedby={`file-${file.id}`} className="shrink-0">
          {t("download")}
        </Button>
        <span id={`file-${file.id}`} hidden>
          {file.file_name}
        </span>
      </div>
      {problem ? <Alert>{t(problem)}</Alert> : null}
    </li>
  );
}

/** "Report" under someone else's message, or, once reported, the line saying what happens next (it takes focus). */
function ReportControl({
  reported,
  onOpen,
  describedBy,
}: {
  reported?: "reported" | "reportedAgain";
  onOpen: () => void;
  describedBy: string;
}) {
  const t = useStrings("trackerMessages");
  const status = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (reported) status.current?.focus();
  }, [reported]);
  if (reported) {
    return (
      <p ref={status} tabIndex={-1} role="status" data-reported={reported} className="flex items-start gap-2 text-sm text-ink focus:outline-none">
        <CheckIcon className="mt-0.5 size-4 shrink-0 text-ok" />
        {t(reported)}
      </p>
    );
  }
  return (
    <Button variant="link" className="self-start text-sm" aria-describedby={describedBy} onClick={onOpen} data-report="">
      {t("report")}
    </Button>
  );
}
