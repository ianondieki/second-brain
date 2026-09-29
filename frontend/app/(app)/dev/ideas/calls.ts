import { api, withCsrf, type ApiClient } from "@/lib/api/client";

import type {
  Attachment,
  Attestations,
  AttestationText,
  DraftBody,
  MyProposal,
  ProblemCard,
  PublishResult,
  Removed,
} from "./ideas";
import {
  publishRefusal,
  saveRefusal,
  uploadRefusal,
  type PublishProblem,
  type Refusal,
  type SaveProblem,
  type UploadProblem,
} from "./outcomes";

// The editor's calls from the browser (same-origin /api through the Next.js rewrite). Each settles into its value or a
// Refusal the screen words; a thrown fetch (offline, reset) is "network".

export type Outcome<T, P extends string> = { ok: true; value: T } | ({ ok: false } & Refusal<P>);

type Answer = { data?: unknown; error?: unknown; response: Response };

async function settle<T, P extends string>(
  call: () => Promise<Answer>,
  refuse: (status: number, body: unknown) => Refusal<P>,
): Promise<Outcome<T, P>> {
  let answer: Answer;
  try {
    answer = await call();
  } catch {
    return { ok: false, ...refuse(0, undefined) };
  }
  if (answer.response.ok) return { ok: true, value: answer.data as T };
  return { ok: false, ...refuse(answer.response.status, answer.error) };
}

/** Save the draft: a new proposal (POST) the first time, then PATCH. */
export function saveDraft(id: string | null, body: DraftBody, client: ApiClient = api) {
  return settle<MyProposal, SaveProblem>(
    () =>
      id
        ? client.PATCH("/api/me/proposals/{proposal_id}", { params: { path: { proposal_id: id } }, body })
        : client.POST("/api/me/proposals", { body }),
    saveRefusal,
  );
}

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
