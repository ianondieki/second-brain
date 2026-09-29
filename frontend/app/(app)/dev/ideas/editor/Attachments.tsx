"use client";

import { useTranslations } from "next-intl";
import { useId, useRef, useState, type ChangeEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import { removeAttachment, uploadAttachment } from "../calls";
import {
  ACCEPT_ATTRIBUTE,
  attachmentType,
  fileSizeParts,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS,
  type Attachment,
} from "../ideas";
import type { UploadProblem } from "../outcomes";

export interface AttachmentsProps {
  attachments: Attachment[];
  onChange: (attachments: Attachment[]) => void;
  /** The proposal's id, creating the draft first when there is none yet; null when that failed. */
  ensureId: () => Promise<string | null>;
  uploadImpl?: typeof uploadAttachment;
  removeImpl?: typeof removeAttachment;
}

type State = { kind: "idle" } | { kind: "uploading"; name: string } | { kind: "problem"; problem: UploadProblem };

/**
 * Files for the full details (Tier 2): PDF, PNG, JPG, Markdown or text, up to 20 MB and ten per version. Each file is
 * sent on its own as soon as it is chosen, scanned by the API before it is kept, and can be removed from the draft.
 */
export function Attachments({
  attachments,
  onChange,
  ensureId,
  uploadImpl = uploadAttachment,
  removeImpl = removeAttachment,
}: AttachmentsProps) {
  const t = useTranslations("ideaEditor");
  const f = useTranslations("ideaFields");
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ kind: "idle" });
  const full = attachments.length >= MAX_ATTACHMENTS;

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // the same file can be chosen again after a refusal
    if (!file || state.kind === "uploading") return;
    const type = attachmentType(file.name);
    if (!type) return setState({ kind: "problem", problem: "wrongType" });
    if (file.size === 0) return setState({ kind: "problem", problem: "empty" });
    if (file.size > MAX_ATTACHMENT_BYTES) return setState({ kind: "problem", problem: "tooLarge" });
    setState({ kind: "uploading", name: file.name });
    const proposalId = await ensureId();
    if (!proposalId) return setState({ kind: "problem", problem: "failed" });
    const outcome = await uploadImpl(proposalId, file, file.name, type);
    if (outcome.ok) {
      onChange([...attachments, outcome.value]);
      setState({ kind: "idle" });
    } else {
      setState({ kind: "problem", problem: outcome.problem });
    }
  }

  async function remove(attachment: Attachment) {
    const proposalId = await ensureId();
    if (!proposalId) return;
    const outcome = await removeImpl(proposalId, attachment.id);
    if (outcome.ok || outcome.problem === "notFound") onChange(attachments.filter((a) => a.id !== attachment.id));
    else setState({ kind: "problem", problem: outcome.problem });
  }

  const hintId = `${id}-hint`;
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
                      {f("fileSize", fileSizeParts(attachment.size_bytes))}
                    </span>
                  ) : null}
                  {attachment.av_status !== "clean" ? (
                    <span className="ml-2 text-sm text-ink-soft">{f("fileScanning")}</span>
                  ) : null}
                </span>
                <Button
                  variant="link"
                  className="shrink-0"
                  aria-label={t("removeFile", { name })}
                  onClick={() => remove(attachment)}
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
        {state.kind === "uploading" ? t("uploading", { name: state.name }) : null}
      </p>

      {full ? null : (
        <div>
          {/* The real input stays in the accessibility tree and takes focus; the label is its visible button. */}
          <input
            ref={input}
            id={`${id}-file`}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            aria-describedby={hintId}
            onChange={choose}
            className="peer sr-only"
          />
          <label
            htmlFor={`${id}-file`}
            className={cn(
              "inline-flex min-h-12 cursor-pointer items-center justify-center rounded-control border border-ink-soft px-5",
              "font-semibold text-ink hover:bg-jacaranda-wash",
              "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-jacaranda",
              state.kind === "uploading" && "cursor-progress",
            )}
          >
            {t("addFile")}
          </label>
        </div>
      )}
    </section>
  );
}
