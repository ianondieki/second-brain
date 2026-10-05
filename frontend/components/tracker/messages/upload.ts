import { ensureCsrf, CSRF_HEADER } from "@/lib/api/csrf";

import type { UploadOptions, UploadOutcome } from "./calls";
import { refusedAttachmentId, retryMinutes, uploadRefusal, type StagedFile } from "./thread";

// The upload itself (REQ-ENG-11), loaded with the first file a person chooses (./calls uploadFile).

/**
 * Stages one file for the caller's next message: the raw bytes as the body, the type in Content-Type, the name
 * percent-encoded in X-File-Name (never in the URL, which reaches access logs). The API scans the file before it
 * answers: clean, it is staged; infected, 422 with the refused record's id.
 */
export async function stageFile(engagementId: string, file: Blob & { name: string }, options: UploadOptions): Promise<UploadOutcome> {
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

