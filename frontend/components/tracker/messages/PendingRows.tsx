"use client";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { AlertIcon, CheckIcon, ClockIcon } from "@/components/ui/status-icons";

import { FileIcon } from "./FileIcon";
import { fileProblemKey, fileSize, maxMegabytes, postRefusalKey, type FileProblem, type Limits, type PostRefusal } from "./thread";

// The composer's file rows (REQ-ENG-11), loaded with the first file a person chooses (Composer.tsx).

export type Status = "uploading" | "scanning" | "ready" | "blocked";

/** A file chosen for the next message: uploading, being scanned, staged (ready) or refused (blocked). */
export interface Pending {
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

/** The chosen files, one row each: name, size, status (an icon, words and a colour) and Remove. */
export function PendingRows({
  files,
  locale,
  limits,
  onRemove,
}: {
  files: readonly Pending[];
  locale: string;
  limits: Limits;
  onRemove: (file: Pending) => void;
}) {
  return files.map((file) => <PendingRow key={file.key} file={file} locale={locale} limits={limits} onRemove={() => onRemove(file)} />);
}

function PendingRow({ file, locale, limits, onRemove }: { file: Pending; locale: string; limits: Limits; onRemove: () => void }) {
  const t = useStrings("trackerMessages");
  const Icon = STATUS_ICON[file.status];
  const status =
    file.status === "uploading" ? t("status.uploading", { value: file.progress }) : t(`status.${file.status}`);
  const problem = file.problem
    ? (file.problem in FILE_KEYS
        ? t(fileProblemKey(file.problem as FileProblem, file.minutes ?? 1, locale), {
            value: maxMegabytes(limits),
            max: limits.max_attachments,
            count: file.minutes ?? 1,
          })
        : t(postRefusalKey(file.problem as PostRefusal, file.minutes ?? 1, locale), { count: file.minutes ?? 1, max: limits.max_attachments }))
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
        <Button variant="link" className="shrink-0" aria-describedby={nameId} onClick={onRemove} data-remove={file.key}>
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
