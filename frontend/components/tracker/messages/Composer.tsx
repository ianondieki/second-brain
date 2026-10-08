"use client";

import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { TextAreaField } from "@/components/ui/TextAreaField";

import type { ThreadCalls } from "./calls";
import type { AttachContext } from "./attach";
import { ClipIcon } from "./FileIcon";
import type { Pending } from "./PendingRows";
import {
  METER_FROM,
  REFRESH_REFUSALS,
  TEXT_REFUSALS,
  maxMegabytes,
  postRefusalKey,
  type Limits,
  type Message,
  type PostRefusal,
} from "./thread";

// The file rows load with the first file chosen (the Messages route sits near its 150 KB; docs/spec/07 item 5).
const PendingRows = lazy(() => import("./PendingRows").then((m) => ({ default: m.PendingRows })));
// Choosing, uploading and removing files load with the first file chosen (./attach.ts); once loaded, every composer
// answers at once (a Remove, only shown once a file was chosen, always does).
let attach: typeof import("./attach") | null = null;

const BODY_ID = "message-body";

export interface ComposerProps {
  engagementId: string;
  limits: Limits;
  locale: string;
  calls: ThreadCalls;
  /** A message was sent: the thread shows it last. */
  onSent: (message: Message) => void;
  /** The thread closed or is not the caller's to write in (a refusal said so): the page is read again. */
  onClosed: () => void;
}

/**
 * The composer (REQ-ENG-11): plain text up to the limit (a count shows near it), files attached one by one as they
 * are chosen (each uploads, is scanned, then shows Ready or Blocked, and can be removed before sending), and Send,
 * the tab's one primary action. Every refusal is a fixed sentence: one about the text on the text box, the rest
 * above the buttons.
 */
export function Composer({ engagementId, limits, locale, calls, onSent, onClosed }: ComposerProps) {
  const t = useStrings("trackerMessages");
  const [text, setText] = useState("");
  const [files, setFiles] = useState<Pending[]>([]);
  const [refusal, setRefusal] = useState<{ kind: PostRefusal; minutes?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const picker = useRef<HTMLInputElement>(null);
  const form = useRef<HTMLFormElement>(null);
  // Files removed while the API scanned them: the upload finishes, then its staged record is deleted.
  const discarded = useRef(new Set<string>());
  const alert = useRef<HTMLDivElement>(null);
  const uploads = useRef(new Map<string, AbortController>());
  const counter = useRef(0);

  useEffect(() => {
    const running = uploads.current;
    const dropped = discarded.current;
    // Leaving the page stops the uploads still running, except a removed file the API is scanning: its answer still
    // comes, and its staged record is deleted then (./attach.ts).
    return () => running.forEach((controller, key) => (dropped.has(key) ? undefined : controller.abort()));
  }, []);

  const length = Array.from(text).length;
  const left = limits.max_chars - length;
  const textRefusal = refusal && TEXT_REFUSALS.has(refusal.kind) ? refusal : null;
  const otherRefusal = refusal && !TEXT_REFUSALS.has(refusal.kind) ? refusal : null;

  function refuse(kind: PostRefusal, minutes?: number) {
    setRefusal({ kind, minutes });
    if (TEXT_REFUSALS.has(kind)) document.getElementById(BODY_ID)?.focus();
    else requestAnimationFrame(() => alert.current?.focus());
    if (REFRESH_REFUSALS.has(kind)) onClosed();
  }

  // What ./attach.ts works with: the composer's state and refs, and how it words things.
  const context = (): AttachContext => ({
    engagementId,
    limits,
    calls,
    files,
    setFiles,
    discarded,
    uploads,
    counter,
    form,
    refuse,
    clearRefusal: () => setRefusal(null),
    sayStatus: (name, ready) => setSaid(t("fileStatus", { name, value: t(ready ? "status.ready" : "status.blocked") })),
    onClosed,
  });

  function choose(chosen: File[]) {
    if (attach) return attach.choose(context(), chosen);
    import("./attach").then(
      (m) => {
        attach = m;
        m.choose(context(), chosen);
      },
      // Offline or a new deploy: the files cannot be taken now; the sentence says to check the connection.
      () => refuse("attachFailed"),
    );
  }

  function remove(file: Pending) {
    attach?.remove(context(), file);
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!text.trim()) return refuse("blank");
    if (left < 0) return refuse("tooLong");
    if (files.some((file) => file.status === "uploading" || file.status === "scanning")) return refuse("waitUploads");
    if (files.some((file) => file.status === "blocked")) return refuse("blockedFiles");
    setBusy(true);
    setRefusal(null);
    let outcome: Awaited<ReturnType<ThreadCalls["postMessage"]>>;
    try {
      outcome = await calls.postMessage(
        engagementId,
        text,
        files.flatMap((file) => (file.id ? [file.id] : [])),
      );
    } catch {
      outcome = { ok: false, refusal: "network" };
    } finally {
      setBusy(false);
    }
    if (!outcome.ok) return refuse(outcome.refusal, outcome.minutes);
    onSent(outcome.message);
    setText("");
    setFiles([]);
    setSaid(t("sent"));
    document.getElementById(BODY_ID)?.focus();
  }

  const refusalText = (kind: PostRefusal, minutes?: number) =>
    t(postRefusalKey(kind, minutes ?? 1, locale), {
      max: kind === "tooLong" ? limits.max_chars : limits.max_attachments,
      count: minutes ?? 1,
    });

  return (
    <form
      ref={form}
      noValidate
      onSubmit={(event) => void send(event)}
      data-composer=""
      // From 1024 px the composer stays at the foot of the screen while the thread scrolls (P25); phones keep the
      // whole height for the thread and the tab bar.
      className="mt-2 flex flex-col gap-4 rounded-panel border border-line bg-field p-4 shadow-card sm:p-5 lg:sticky lg:bottom-4 lg:z-[5]"
    >
      <TextAreaField
        id={BODY_ID}
        name="body"
        label={t("label")}
        rows={3}
        value={text}
        onChange={(event) => {
          setText(event.currentTarget.value);
          if (textRefusal) setRefusal(null);
        }}
        error={textRefusal ? refusalText(textRefusal.kind) : undefined}
        meter={
          left <= METER_FROM ? (
            <span data-meter={left < 0 ? "over" : "left"} className={cn(left < 0 && "font-semibold text-error")}>
              {left < 0 ? t("meterOver", { count: -left }) : t("meterLeft", { count: left })}
            </span>
          ) : undefined
        }
      />

      {files.length > 0 ? (
        <ul aria-label={t("files")} className="flex flex-col gap-2" data-pending-files="">
          <Suspense fallback={null}>
            <PendingRows files={files} locale={locale} limits={limits} onRemove={remove} />
          </Suspense>
        </ul>
      ) : null}

      {otherRefusal ? <Alert ref={alert}>{refusalText(otherRefusal.kind, otherRefusal.minutes)}</Alert> : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        {/* A thread without files (a team thread: max_attachments 0) has no Attach; Send keeps its place. */}
        {limits.max_attachments ? (
          <div className="flex flex-col items-start gap-1">
            <Button variant="secondary" aria-describedby="attach-hint" onClick={() => picker.current?.click()} data-attach="">
              <ClipIcon className="mr-2 size-5" />
              {t("attach")}
            </Button>
            <p id="attach-hint" className="max-w-[40ch] text-xs text-ink-soft">
              {t("attachHint", { value: maxMegabytes(limits), max: limits.max_attachments })}
            </p>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              accept={[...limits.accepted_types, ".md", ".markdown", ".txt"].join(",")}
              onChange={(event) => {
                choose(Array.from(event.currentTarget.files ?? []));
                event.currentTarget.value = "";
              }}
            />
          </div>
        ) : (
          <span />
        )}
        <Button type="submit" variant="primary" busy={busy} data-send="">
          {busy ? t("sending") : t("send")}
        </Button>
      </div>
      <p aria-live="polite" className="sr-only" data-composer-said="">
        {said}
      </p>
    </form>
  );
}
