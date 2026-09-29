import { queryString, withCsrf } from "@/lib/api/client";

import { MAX_UPLOAD_BYTES, UPLOAD_PATH, type UploadCheck } from "./certificate";

export type FileProblem = "noFile" | "tooLarge" | "rateLimited" | "failed" | "network";

export type FileOutcome = { ok: true; result: UploadCheck } | { ok: false; problem: FileProblem };

type Send = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** What stops a file before any request: none chosen, or over the API's 10 MB limit. */
export function fileProblem(file: File | undefined | null): FileProblem | null {
  if (!file) return "noFile";
  return file.size > MAX_UPLOAD_BYTES ? "tooLarge" : null;
}

/**
 * POST /api/verify[?cert_id=] with the file's bytes as the body (the API hashes the stream and keeps nothing). The
 * typed client sends JSON bodies only, so this is the one raw-body call; it still goes through withCsrf, since the
 * API checks the double-submit token on every POST. A thrown fetch is "network"; 413 is "tooLarge"; 429
 * "rateLimited"; anything else unexpected "failed".
 */
export async function checkFile(file: Blob, certId?: string, send: Send = withCsrf()): Promise<FileOutcome> {
  let response: Response;
  try {
    response = await send(`${UPLOAD_PATH}${queryString({ cert_id: certId })}`, {
      method: "POST",
      body: file,
      credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream", Accept: "application/json" },
    });
  } catch {
    return { ok: false, problem: "network" };
  }
  if (response.status === 413) return { ok: false, problem: "tooLarge" };
  if (response.status === 429) return { ok: false, problem: "rateLimited" };
  if (!response.ok) return { ok: false, problem: "failed" };
  try {
    const result = (await response.json()) as UploadCheck;
    return typeof result?.match === "boolean" ? { ok: true, result } : { ok: false, problem: "failed" };
  } catch {
    return { ok: false, problem: "failed" };
  }
}
