"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { AlertIcon, CheckIcon, ClockIcon } from "@/components/ui/status-icons";
import { TextAreaField } from "@/components/ui/TextAreaField";

import type { ThreadCalls } from "./calls";
import { ClipIcon, FileIcon } from "./FileIcon";
import {
  METER_FROM,
  REFRESH_REFUSALS,
  TEXT_REFUSALS,
  contentTypeOf,
  fileProblem,
  fileSize,
  maxMegabytes,
  type FileProblem,
  type Limits,
  type Message,
  type PostRefusal,
} from "./thread";

type Status = "uploading" | "scanning" | "ready" | "blocked";

/** A file chosen for the next message: uploading, being scanned, staged (ready) or refused (blocked). */
interface Pending {
  key: string;
  name: string;
  size: number;
  status: Status;
  progress: number;
  /** The staged upload's id (ready), or a refused upload's record (blocked by the scan), which Remove deletes. */
  id: string | null;
  problem: FileProblem | PostRefusal | null;
  minutes?: number;
}

const STATUS_ICON = { uploading: ClockIcon, scanning: ClockIcon, ready: CheckIcon, blocked: AlertIcon } as const;
const STATUS_TONE = { uploading: "text-ink-soft", scanning: "text-ink-soft", ready: "text-ok", blocked: "text-error" } as const;

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
  const alert = useRef<HTMLDivElement>(null);
  const uploads = useRef(new Map<string, AbortController>());
  const counter = useRef(0);

  useEffect(() => {
    const running = uploads.current;
    return () => running.forEach((controller) => controller.abort());
  }, []);

  const length = Array.from(text).length;
  const left = limits.max_chars - length;
  const textRefusal = refusal && TEXT_REFUSALS.has(refusal.kind) ? refusal : null;
  const otherRefusal = refusal && !TEXT_REFUSALS.has(refusal.kind) ? refusal : null;

  function update(key: string, change: Partial<Pending>) {
    setFiles((now) => now.map((file) => (file.key === key ? { ...file, ...change } : file)));
  }

  function refuse(kind: PostRefusal, minutes?: number) {
    setRefusal({ kind, minutes });
    if (TEXT_REFUSALS.has(kind)) document.getElementById(BODY_ID)?.focus();
    else requestAnimationFrame(() => alert.current?.focus());
    if (REFRESH_REFUSALS.has(kind)) onClosed();
  }

  async function upload(key: string, file: File) {
    const controller = new AbortController();
    uploads.current.set(key, controller);
    const outcome = await calls.uploadFile(engagementId, file, {
      contentType: contentTypeOf(file),
      signal: controller.signal,
      onProgress: (percent) => update(key, percent < 100 ? { progress: percent } : { progress: 100, status: "scanning" }),
    });
    uploads.current.delete(key);
    if (controller.signal.aborted) return;
    if (outcome.ok) {
      update(key, { status: "ready", id: outcome.file.id, progress: 100 });
      setSaid(t("fileStatus", { name: file.name, value: t("status.ready") }));
      return;
    }
    update(key, { status: "blocked", problem: outcome.problem, minutes: outcome.minutes, id: outcome.attachmentId ?? null });
    setSaid(t("fileStatus", { name: file.name, value: t("status.blocked") }));
    if (REFRESH_REFUSALS.has(outcome.problem as PostRefusal)) onClosed();
  }

  function choose(list: FileList | null) {
    if (!list || list.length === 0) return;
    setRefusal(null);
    const room = limits.max_attachments - files.filter((file) => file.status !== "blocked").length;
    const chosen = Array.from(list);
    if (chosen.length > room) refuse("tooManyFiles");
    const added = chosen.slice(0, Math.max(0, room)).map((file) => {
      counter.current += 1;
      const problem = fileProblem(file, limits);
      const pending: Pending = {
        key: `file-${counter.current}`,
        name: file.name,
        size: file.size,
        status: problem ? "blocked" : "uploading",
        progress: 0,
        id: null,
        problem,
      };
      return { file, pending };
    });
    // The rows first, then the uploads, so every progress report finds its row.
    setFiles((now) => [...now, ...added.map(({ pending }) => pending)]);
    for (const { file, pending } of added) if (!pending.problem) void upload(pending.key, file);
  }

  function remove(file: Pending) {
    uploads.current.get(file.key)?.abort();
    uploads.current.delete(file.key);
    setFiles((now) => now.filter((f) => f.key !== file.key));
    if (file.id) void calls.removeStaged(engagementId, file.id);
    setRefusal(null);
    picker.current?.focus();
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
    const outcome = await calls.postMessage(
      engagementId,
      text,
      files.flatMap((file) => (file.id ? [file.id] : [])),
    );
    setBusy(false);
    if (!outcome.ok) return refuse(outcome.refusal, outcome.minutes);
    onSent(outcome.message);
    setText("");
    setFiles([]);
    setSaid(t("sent"));
    document.getElementById(BODY_ID)?.focus();
  }

  const refusalText = (kind: PostRefusal, minutes?: number) =>
    t(`refusal.${kind}`, { max: kind === "tooLong" ? limits.max_chars : limits.max_attachments, count: minutes ?? 1 });

  return (
    <form
      noValidate
      onSubmit={(event) => void send(event)}
      data-composer=""
      className="mt-2 flex flex-col gap-4 rounded-panel border border-line bg-field p-4 shadow-card sm:p-5"
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
          {files.map((file) => (
            <PendingRow key={file.key} file={file} locale={locale} limits={limits} onRemove={() => remove(file)} />
          ))}
        </ul>
      ) : null}

      {otherRefusal ? <Alert ref={alert}>{refusalText(otherRefusal.kind, otherRefusal.minutes)}</Alert> : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
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
              choose(event.currentTarget.files);
              event.currentTarget.value = "";
            }}
          />
        </div>
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

function PendingRow({ file, locale, limits, onRemove }: { file: Pending; locale: string; limits: Limits; onRemove: () => void }) {
  const t = useStrings("trackerMessages");
  const Icon = STATUS_ICON[file.status];
  const status =
    file.status === "uploading" ? t("status.uploading", { value: file.progress }) : t(`status.${file.status}`);
  const problem = file.problem
    ? (file.problem in FILE_KEYS
        ? t(`file.${file.problem as FileProblem}`, { value: maxMegabytes(limits), max: limits.max_attachments, count: file.minutes ?? 1 })
        : t(`refusal.${file.problem as PostRefusal}`, { count: file.minutes ?? 1, max: limits.max_attachments }))
    : null;
  const nameId = `${file.key}-name`;
  return (
    <li data-pending-file={file.name} data-status={file.status} className="flex flex-col gap-1.5">
      <div
        className={cn(
          "flex min-h-11 items-center gap-3 rounded-control border py-1 pr-1 pl-3",
          file.status === "blocked" ? "border-error-line bg-error-wash" : "border-line bg-paper",
        )}
      >
        <FileIcon className="size-5 shrink-0 text-accent" />
        <span className="min-w-0 flex-1">
          <span id={nameId} className="block truncate text-sm font-semibold text-ink">
            {file.name}
          </span>
          {/* Ink, not ink-soft, on the blocked row's error wash (never grey text on a coloured surface). */}
          <span className={cn("flex flex-wrap gap-x-3 text-xs tabular-nums", file.status === "blocked" ? "text-ink" : "text-ink-soft")}>
            <span>{fileSize(file.size, locale)}</span>
            <span className={cn("inline-flex items-center gap-1 font-semibold", STATUS_TONE[file.status])} data-file-status={file.status}>
              <Icon className="size-3.5" />
              {status}
            </span>
          </span>
        </span>
        <Button variant="link" className="shrink-0" aria-describedby={nameId} onClick={onRemove}>
          {t("remove")}
        </Button>
      </div>
      {file.status === "uploading" ? (
        <ProgressBar value={file.progress} max={100} segments={false} label={status} />
      ) : null}
      {problem ? <p className="text-sm text-error">{problem}</p> : null}
    </li>
  );
}

const FILE_KEYS: Record<FileProblem, true> = {
  type: true,
  size: true,
  empty: true,
  infected: true,
  tooMany: true,
  staged: true,
  limit: true,
  storage: true,
  failed: true,
};
