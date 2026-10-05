import { api, ensureCsrf, CSRF_HEADER, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";

import {
  postRefusal,
  refusedAttachmentId,
  reportRefusal,
  retryMinutes,
  uploadRefusal,
  type FileProblem,
  type Message,
  type PostRefusal,
  type ReportReason,
  type ReportRefusal,
  type StagedFile,
  type Thread,
} from "./thread";

// The thread's calls from the browser (REQ-ENG-11; same-origin /api through the Next.js rewrite; the typed client adds
// the CSRF header to every POST and DELETE). Each settles into its value or a refusal the thread words; a thrown fetch
// (offline, reset) is "network". The upload is a raw XMLHttpRequest, the one way a browser reports upload progress.

const THREAD = "/api/engagements/{engagement_id}/messages" as const;

export type PostOutcome = { ok: true; message: Message } | { ok: false; refusal: PostRefusal; minutes?: number };

export async function postMessage(
  engagementId: string,
  body: string,
  attachmentIds: string[],
  client: ApiClient = api,
): Promise<PostOutcome> {
  try {
    const { data, error, response } = await client.POST(THREAD, {
      params: { path: { engagement_id: engagementId } },
      body: { body, attachment_ids: attachmentIds },
    });
    if (data) return { ok: true, message: data };
    const refusal = postRefusal(response.status, error);
    return refusal === "tooMany" ? { ok: false, refusal, minutes: retryMinutes(response.headers, error) } : { ok: false, refusal };
  } catch {
    return { ok: false, refusal: "network" };
  }
}

export type PageOutcome = { ok: true; thread: Thread } | { ok: false };

/** The page of the thread before `cursor` (older messages). */
export async function olderPage(engagementId: string, cursor: string, client: ApiClient = api): Promise<PageOutcome> {
  try {
    const { data } = await client.GET(THREAD, { params: { path: { engagement_id: engagementId }, query: { cursor } } });
    return data ? { ok: true, thread: data } : { ok: false };
  } catch {
    return { ok: false };
  }
}

/** Moves the caller's read marker up to a message they have seen. Quiet: a refusal changes nothing on the page. */
export async function markRead(engagementId: string, upTo: string, client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.POST(`${THREAD}/read`, {
      params: { path: { engagement_id: engagementId } },
      body: { up_to: upTo },
    });
    return response.ok;
  } catch {
    return false;
  }
}

export type ReportOutcome = { ok: true; created: boolean } | { ok: false; refusal: ReportRefusal };

export async function reportMessage(
  engagementId: string,
  messageId: string,
  reasons: ReportReason[],
  client: ApiClient = api,
): Promise<ReportOutcome> {
  try {
    const { data, error, response } = await client.POST(`${THREAD}/{message_id}/report`, {
      params: { path: { engagement_id: engagementId, message_id: messageId } },
      body: { reasons },
    });
    if (data) return { ok: true, created: data.created };
    return { ok: false, refusal: reportRefusal(response.status, error) };
  } catch {
    return { ok: false, refusal: "reportFailed" };
  }
}

export type LinkOutcome = { ok: true; url: string } | { ok: false; changed: boolean };

/** A short-lived link to a sent file, signed for the caller; the browser then opens it (a download). */
export async function fileLink(
  engagementId: string,
  messageId: string,
  attachmentId: string,
  client: ApiClient = api,
): Promise<LinkOutcome> {
  try {
    const { data, error } = await client.GET(`${THREAD}/{message_id}/attachments/{attachment_id}`, {
      params: { path: { engagement_id: engagementId, message_id: messageId, attachment_id: attachmentId } },
    });
    return data ? { ok: true, url: data.url } : { ok: false, changed: apiErrorCode(error) === "file_changed" };
  } catch {
    return { ok: false, changed: false };
  }
}

/** Removes one of the caller's staged (not yet sent) files, or the record of a refused one. */
export async function removeStaged(engagementId: string, attachmentId: string, client: ApiClient = api): Promise<boolean> {
  try {
    const { response } = await client.DELETE(`${THREAD}/attachments/{attachment_id}`, {
      params: { path: { engagement_id: engagementId, attachment_id: attachmentId } },
    });
    return response.ok || response.status === 404;
  } catch {
    return false;
  }
}

export type UploadOutcome =
  | { ok: true; file: StagedFile }
  | { ok: false; problem: FileProblem | PostRefusal; minutes?: number; attachmentId?: string | null };

export interface UploadOptions {
  contentType: string;
  /** Upload progress, 0 to 100; 100 once every byte is sent (the scan runs before the answer comes). */
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

/**
 * Stages one file for the caller's next message: the raw bytes as the body, the type in Content-Type, the name
 * percent-encoded in X-File-Name (never in the URL, which reaches access logs). The API scans the file before it
 * answers: clean, it is staged; infected, 422 with the refused record's id.
 */
export async function uploadFile(engagementId: string, file: Blob & { name: string }, options: UploadOptions): Promise<UploadOutcome> {
  let token: string | undefined;
  try {
    token = await ensureCsrf();
  } catch {
    return { ok: false, problem: "failed" };
  }
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/engagements/${encodeURIComponent(engagementId)}/messages/attachments`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", options.contentType);
    xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    xhr.setRequestHeader("Accept", "application/json");
    if (token) xhr.setRequestHeader(CSRF_HEADER, token);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    };
    xhr.upload.onload = () => options.onProgress?.(100);
    xhr.onerror = () => resolve({ ok: false, problem: "failed" });
    xhr.onabort = () => resolve({ ok: false, problem: "failed" });
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 201 && body) {
        resolve({ ok: true, file: body as StagedFile });
        return;
      }
      const problem = uploadRefusal(xhr.status, body);
      const headers = { get: (name: string) => xhr.getResponseHeader(name) };
      resolve({
        ok: false,
        problem,
        minutes: problem === "limit" ? retryMinutes(headers, body) : undefined,
        attachmentId: refusedAttachmentId(body),
      });
    };
    options.signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}
