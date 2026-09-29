"use client";

import { useId, useState, type ChangeEvent } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import type { Calls } from "../calls";
import { ACCEPT_ATTRIBUTE, attachmentType, fileSizeParts, MAX_FILE_NAME_HEADER } from "../files";
import { MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, type Attachment } from "../ideas";
import type { SaveProblem, UploadProblem } from "../outcomes";

export type DraftReady = { id: string; attachments: Attachment[] } | { problem: SaveProblem };

export interface AttachmentsProps {
  attachments: Attachment[];
  /** Changes the list from its latest value (never from a copy this component holds). */
  onAttachments: (change: (list: Attachment[]) => Attachment[]) => void;
  /** Drafts and saves first: a published idea's files get new ids in the new draft version. */
  ensureDraft: () => Promise<DraftReady>;
  getCalls: () => Promise<Calls>;
}

type Problem = UploadProblem | "notSaved" | "fileGone";
type State = { kind: "idle" } | { kind: "busy"; name?: string } | { kind: "problem"; problem: Problem };

/** Why a file cannot be added before anything is sent, or null. */
function fileProblem(file: File): Problem | null {
  if (!attachmentType(file.name)) return "wrongType";
  if (file.size === 0) return "empty";
  if (file.size > MAX_ATTACHMENT_BYTES) return "tooLarge";
  if (encodeURIComponent(file.name).length > MAX_FILE_NAME_HEADER) return "badName";
  return null;
}

function saveProblem(problem: SaveProblem): Problem {
  return problem === "fields" || problem === "validation" ? "notSaved" : problem;
}

/**
 * Files for the full details (Tier 2): PDF, PNG, JPG, Markdown or text, up to 20 MB and ten per version. Every action
 * first makes sure the draft exists and is saved, then works on the draft's own files: removing a file of a published
 * idea removes the draft's copy, never the registered version's (which stays as it was registered). A file the API
 * did not remove stays listed.
 */
export function Attachments({ attachments, onAttachments, ensureDraft, getCalls }: AttachmentsProps) {
  const t = useStrings("ideaEditor");
  const f = useStrings("ideaFields");
  const id = useId();
  const [state, setState] = useState<State>({ kind: "idle" });
  const busy = state.kind === "busy";
  const fileSize = (bytes: number) => {
    const { key, value } = fileSizeParts(bytes);
    return f(key, { value });
  };

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // the same file can be chosen again after a refusal
    if (!file || busy) return;
    const early = fileProblem(file);
    if (early) return setState({ kind: "problem", problem: early });
    setState({ kind: "busy", name: file.name });
    const ready = await ensureDraft();
    if ("problem" in ready) return setState({ kind: "problem", problem: saveProblem(ready.problem) });
    const calls = await getCalls().catch(() => null);
    if (!calls) return setState({ kind: "problem", problem: "network" });
    const outcome = await calls.uploadAttachment(ready.id, file, file.name, attachmentType(file.name)!);
    if (!outcome.ok) return setState({ kind: "problem", problem: outcome.problem });
    onAttachments((list) => [...list, outcome.value]);
    setState({ kind: "idle" });
  }

  async function remove(attachment: Attachment) {
    if (busy) return;
    setState({ kind: "busy" });
    const ready = await ensureDraft();
    if ("problem" in ready) return setState({ kind: "problem", problem: saveProblem(ready.problem) });
    // The draft's own copy: the same id, or (right after a published idea was drafted) the same file under a new id.
    const target =
      ready.attachments.find((a) => a.id === attachment.id) ??
      ready.attachments.find((a) => a.sha256 === attachment.sha256 && a.file_name === attachment.file_name);
    if (!target) return setState({ kind: "problem", problem: "fileGone" });
    const calls = await getCalls().catch(() => null);
    if (!calls) return setState({ kind: "problem", problem: "network" });
    const outcome = await calls.removeAttachment(ready.id, target.id);
    if (!outcome.ok) {
      return setState({ kind: "problem", problem: outcome.problem === "notFound" ? "fileGone" : outcome.problem });
    }
    onAttachments((list) => list.filter((a) => a.id !== target.id));
    setState({ kind: "idle" });
  }

  const hintId = `${id}-hint`;
  const full = attachments.length >= MAX_ATTACHMENTS;
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3">
      <h3 id={`${id}-title`} className="font-medium text-ink">
        {f("files")}
      </h3>
      <p id={hintId} className="-mt-2 text-sm text-ink-soft">
        {t("filesHint", { max: MAX_ATTACHMENTS })}
      </p>

      {attachments.length > 0 ? (
        <ul aria-label={t("filesLabel")} className="flex flex-col">
          {attachments.map((attachment) => {
            const name = attachment.file_name ?? attachment.id;
            return (
              <li
                key={attachment.id}
                className="flex items-start justify-between gap-3 border-t border-line py-1.5 last:border-b"
              >
                <span className="min-w-0 pt-2.5 [overflow-wrap:anywhere]">
                  {name}
                  {attachment.size_bytes !== null ? (
                    <span className="ml-2 text-sm text-ink-soft tabular-nums">
                      {fileSize(attachment.size_bytes)}
                    </span>
                  ) : null}
                  {attachment.av_status !== "clean" ? (
                    <span className="ml-2 text-sm text-ink-soft">{f("fileScanning")}</span>
                  ) : null}
                </span>
                <Button
                  variant="link"
                  className="shrink-0"
                  busy={busy}
                  aria-label={t("removeFile", { name })}
                  onClick={() => void remove(attachment)}
                >
                  {t("unlink")}
                </Button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {state.kind === "problem" ? <Alert>{t(`problem.${state.problem}`)}</Alert> : null}
      <p role="status" className="text-sm text-ink-soft empty:hidden">
        {state.kind === "busy" && state.name ? t("uploading", { name: state.name }) : null}
      </p>

      {full ? null : (
        <div>
          {/* The real input stays in the accessibility tree and takes focus; the label is its visible button. */}
          <input
            id={`${id}-file`}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            aria-describedby={hintId}
            disabled={busy}
            onChange={choose}
            className="peer sr-only"
          />
          <label
            htmlFor={`${id}-file`}
            className={cn(
              "inline-flex min-h-12 cursor-pointer items-center justify-center rounded-control border border-ink-soft px-5",
              "font-semibold text-ink hover:bg-jacaranda-wash",
              "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-jacaranda",
              "peer-disabled:cursor-progress peer-disabled:border-line peer-disabled:text-ink-soft",
            )}
          >
            {t("addFile")}
          </label>
        </div>
      )}
    </section>
  );
}
