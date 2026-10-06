import { apiErrorCode, detailOf } from "@/lib/api/error-code";

import type { FileProblem, Limits, PostRefusal, ReportRefusal } from "./thread";

// The words for the API's answers to a thread's calls, and the file checks before an upload (REQ-ENG-11): only the
// calls (./calls.ts, ./upload.ts, a team thread's) and the files' code (./attach.ts) need them, and those load on first
// use, so this module never ships with a thread's route (docs/spec/07 item 5).

/** The type the API is sent: the browser's, or by the name's ending for Markdown and text files it leaves blank. */
export function contentTypeOf(file: Pick<File, "name" | "type">): string {
  if (file.type) return file.type === "text/x-markdown" ? "text/markdown" : file.type;
  const name = file.name.toLowerCase();
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "text/markdown";
  if (name.endsWith(".txt")) return "text/plain";
  return "";
}

/** Why a chosen file cannot be uploaded, before anything is sent (the API checks the same again), or null. */
export function fileProblem(file: Pick<File, "name" | "type" | "size">, limits: Limits): FileProblem | null {
  if (!limits.accepted_types.includes(contentTypeOf(file))) return "type";
  if (file.size === 0) return "empty";
  if (file.size > limits.max_attachment_bytes) return "size";
  return null;
}

const POST_CODES: Record<string, PostRefusal> = {
  contains_contact: "containsContact",
  attachment_pending: "pending",
  unknown_attachment: "unknownFile",
  attachment_infected: "infected",
  attachment_expired: "expired",
  too_many_attachments: "tooManyFiles",
  thread_not_open: "notOpen",
  thread_read_only: "readOnly",
  cannot_post: "cannotPost",
  too_many_messages: "tooMany",
  conflict: "conflict",
};

export function postRefusal(status: number, error: unknown): PostRefusal {
  const code = apiErrorCode(error);
  if (code && code in POST_CODES) return POST_CODES[code];
  if (status === 422) return "invalid";
  if (status === 409) return "conflict";
  if (status === 403) return "cannotPost";
  return "generic";
}

const FILE_CODES: Record<string, FileProblem> = {
  unsupported_file: "type",
  too_large: "size",
  empty_file: "empty",
  attachment_infected: "infected",
  too_many_staged: "staged",
  too_many_uploads: "limit",
  upload_quota: "limit",
  storage_unavailable: "storage",
};

/** An upload's refusal; the thread's own refusals (closed, not open) come back as a PostRefusal instead. */
export function uploadRefusal(status: number, error: unknown): FileProblem | PostRefusal {
  const code = apiErrorCode(error);
  if (code && code in FILE_CODES) return FILE_CODES[code];
  if (code === "thread_read_only") return "readOnly";
  if (code === "thread_not_open") return "notOpen";
  if (code === "cannot_post") return "cannotPost";
  if (status === 413) return "size";
  if (status === 429) return "limit";
  if (status === 503) return "storage";
  return "failed";
}

export function reportRefusal(status: number, error: unknown): ReportRefusal {
  const code = apiErrorCode(error);
  if (code === "own_message") return "reportOwn";
  if (code === "too_many_reports" || status === 429) return "reportLimit";
  return "reportFailed";
}

/** Whole minutes until a 429 lifts, from the Retry-After header or the body's `retry_after_seconds` (at least 1). */
export function retryMinutes(headers: Pick<Headers, "get"> | null, error: unknown): number {
  const header = Number(headers?.get("Retry-After"));
  const body = Number(detailOf(error)?.retry_after_seconds);
  const seconds = Number.isFinite(header) && header > 0 ? header : Number.isFinite(body) && body > 0 ? body : 60;
  return Math.max(1, Math.ceil(seconds / 60));
}

/** The id of a refused upload's record, which its uploader may remove (an infected file holds a staging place). */
export function refusedAttachmentId(error: unknown): string | null {
  const id = detailOf(error)?.attachment_id;
  return typeof id === "string" ? id : null;
}
