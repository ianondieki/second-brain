import { api, withCsrf, type ApiClient } from "@/lib/api/client";

import type {
  Attachment,
  Attestations,
  AttestationText,
  ProblemCard,
  PublishResult,
  Removed,
} from "./ideas";
import { saveRefusal, type PublishProblem, type SaveProblem, type UploadProblem } from "./outcomes";
import { publishRefusal, uploadRefusal } from "./refusals";
import { saveDraft, saveState, settle, type Outcome } from "./save";

export { saveDraft, saveState, type Outcome };

// The editor's calls from the browser (same-origin /api through the Next.js rewrite). Each settles into its value or a
// Refusal the screen words; a thrown fetch (offline, reset) is "network".

export function publish(id: string, text: AttestationText, attestations: Attestations, client: ApiClient = api) {
  return settle<PublishResult, PublishProblem>(
    () =>
      client.POST("/api/me/proposals/{proposal_id}/publish", {
        params: { path: { proposal_id: id } },
        body: { attestations, attestation_text_version: text.version },
      }),
    publishRefusal,
  );
}

/** The statements to confirm, read again after the API said the wording changed (409). */
export function attestationText(client: ApiClient = api) {
  return settle<AttestationText, PublishProblem>(() => client.GET("/api/proposals/attestations"), publishRefusal);
}

export function removeIdea(id: string, client: ApiClient = api) {
  return settle<Removed, SaveProblem>(
    () => client.DELETE("/api/me/proposals/{proposal_id}", { params: { path: { proposal_id: id } } }),
    saveRefusal,
  );
}

/** Published problems for the picker: newest first, by niche (a parent includes its children) and words. */
export function searchProblems(filters: { q?: string; niche?: string }, client: ApiClient = api) {
  const q = filters.q?.trim() ? Array.from(filters.q.trim()).slice(0, 100).join("") : undefined;
  return settle<{ items: ProblemCard[] }, SaveProblem>(
    () => client.GET("/api/problems", { params: { query: { q, niche: filters.niche || undefined, limit: 20 } } }),
    saveRefusal,
  );
}

export function removeAttachment(id: string, attachmentId: string, client: ApiClient = api) {
  return settle<undefined, UploadProblem>(
    () =>
      client.DELETE("/api/me/proposals/{proposal_id}/attachments/{attachment_id}", {
        params: { path: { proposal_id: id, attachment_id: attachmentId } },
      }),
    uploadRefusal,
  );
}

type Send = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/**
 * POST the file's bytes as the body, its type in Content-Type and its name percent-encoded in X-File-Name (never in
 * the URL, which reaches access logs). The typed client sends JSON only, so this is a raw call through withCsrf.
 */
export async function uploadAttachment(
  id: string,
  file: Blob,
  name: string,
  contentType: string,
  send: Send = withCsrf(),
): Promise<Outcome<Attachment, UploadProblem>> {
  let response: Response;
  try {
    response = await send(`/api/me/proposals/${encodeURIComponent(id)}/attachments`, {
      method: "POST",
      body: file,
      credentials: "same-origin",
      headers: { "Content-Type": contentType, "X-File-Name": encodeURIComponent(name), Accept: "application/json" },
    });
  } catch {
    return { ok: false, ...uploadRefusal(0, undefined) };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  if (response.ok && body) return { ok: true, value: body as Attachment };
  return { ok: false, ...uploadRefusal(response.ok ? 500 : response.status, body) };
}

/** What the editor loads on demand (its tests pass fakes). */
export interface Calls {
  saveState: typeof saveState;
  publish: typeof publish;
  attestationText: typeof attestationText;
  uploadAttachment: typeof uploadAttachment;
  removeAttachment: typeof removeAttachment;
}
