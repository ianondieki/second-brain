import type { Dispatch, RefObject, SetStateAction } from "react";

import type { ThreadCalls } from "./calls";
import type { Pending } from "./PendingRows";
import { contentTypeOf, fileProblem } from "./refusals";
import { REFRESH_REFUSALS, type Limits, type PostRefusal } from "./thread";

// The composer's files at work (REQ-ENG-11): choosing, uploading and removing them. Loaded with the first file chosen
// (Composer.tsx), so a thread without files (a team thread, REQ-DEV-03) never loads it and a thread with them only
// once a file is chosen (docs/spec/07 item 5: the routes that draw a thread sit near 150 KB).

/** What the composer lends its files: its state, its refs and how it words things. */
export interface AttachContext {
  engagementId: string;
  limits: Limits;
  calls: ThreadCalls;
  /** The files as the composer last drew them. */
  files: Pending[];
  setFiles: Dispatch<SetStateAction<Pending[]>>;
  /** Files removed while the API scanned them: the upload finishes, then its staged record is deleted. */
  discarded: RefObject<Set<string>>;
  uploads: RefObject<Map<string, AbortController>>;
  counter: RefObject<number>;
  form: RefObject<HTMLFormElement | null>;
  refuse: (kind: PostRefusal) => void;
  clearRefusal: () => void;
  /** The composer's polite live line: a file's status ("plan.md: Ready"). */
  sayStatus: (name: string, ready: boolean) => void;
  onClosed: () => void;
}

function update(ctx: AttachContext, key: string, change: Partial<Pending>) {
  ctx.setFiles((now) => now.map((file) => (file.key === key ? { ...file, ...change } : file)));
}

async function upload(ctx: AttachContext, key: string, file: File) {
  const controller = new AbortController();
  ctx.uploads.current.set(key, controller);
  const outcome = await ctx.calls.uploadFile(ctx.engagementId, file, {
    contentType: contentTypeOf(file),
    signal: controller.signal,
    onProgress: (percent) => update(ctx, key, percent < 100 ? { progress: percent } : { progress: 100, status: "scanning" }),
  });
  ctx.uploads.current.delete(key);
  if (ctx.discarded.current.delete(key)) {
    const staged = outcome.ok ? outcome.file.id : (outcome.attachmentId ?? null);
    if (staged) void ctx.calls.removeStaged(ctx.engagementId, staged);
    return;
  }
  if (controller.signal.aborted) return;
  if (outcome.ok) {
    update(ctx, key, { status: "ready", id: outcome.file.id, progress: 100 });
    ctx.sayStatus(file.name, true);
    return;
  }
  update(ctx, key, { status: "blocked", problem: outcome.problem, minutes: outcome.minutes, id: outcome.attachmentId ?? null });
  ctx.sayStatus(file.name, false);
  if (REFRESH_REFUSALS.has(outcome.problem as PostRefusal)) ctx.onClosed();
}

/** Files chosen: each gets a row (blocked at once when its type, size or emptiness rules it out) and uploads. */
export function choose(ctx: AttachContext, chosen: File[]) {
  if (chosen.length === 0) return;
  ctx.clearRefusal();
  const room = ctx.limits.max_attachments - ctx.files.filter((file) => file.status !== "blocked").length;
  if (chosen.length > room) ctx.refuse("tooManyFiles");
  const added = chosen.slice(0, Math.max(0, room)).map((file) => {
    ctx.counter.current += 1;
    const problem = fileProblem(file, ctx.limits);
    const pending: Pending = {
      key: `file-${ctx.counter.current}`,
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
  ctx.setFiles((now) => [...now, ...added.map(({ pending }) => pending)]);
  for (const { file, pending } of added) if (!pending.problem) void upload(ctx, pending.key, file);
}

/** A file's Remove: its upload stops (or its staged record is deleted) and focus moves to the next Remove or Attach. */
export function remove(ctx: AttachContext, file: Pending) {
  if (file.status === "uploading") {
    // Not every byte has reached the API, so it has kept nothing: the request can stop.
    ctx.uploads.current.get(file.key)?.abort();
    ctx.uploads.current.delete(file.key);
  } else if (file.status === "scanning") {
    // The API holds the file while it scans: let it answer, then delete what it staged (upload above).
    ctx.discarded.current.add(file.key);
  }
  const index = ctx.files.findIndex((f) => f.key === file.key);
  const next = ctx.files[index + 1] ?? ctx.files[index - 1];
  ctx.setFiles((now) => now.filter((f) => f.key !== file.key));
  if (file.id) void ctx.calls.removeStaged(ctx.engagementId, file.id);
  ctx.clearRefusal();
  // Focus goes to the next row's Remove, or to Attach files once no row is left (never to the hidden input).
  requestAnimationFrame(() => {
    const target = next ? `[data-remove="${next.key}"]` : "[data-attach]";
    ctx.form.current?.querySelector<HTMLElement>(target)?.focus();
  });
}
