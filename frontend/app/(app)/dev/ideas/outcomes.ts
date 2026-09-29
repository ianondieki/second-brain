import { apiErrorCode } from "@/lib/api/errors";

import { isFieldName, type FieldIssue } from "./ideas";

// What the editor's calls can answer, as the screen words it (REQ-PROP-01). The API's `detail.message` is never shown:
// every case below has its own [[COPY-REVIEW]] string under `ideaEditor.*`, so it can be translated and reviewed.

/** Problems every call shares. */
export type CommonProblem = "signedOut" | "notFound" | "hidden" | "unavailable" | "network" | "failed";

export type SaveProblem = CommonProblem | "fields" | "validation";

export type PublishProblem =
  | CommonProblem
  | "fields"
  | "d1Required"
  | "planLimit"
  | "attestationsRequired"
  | "attestationsChanged"
  | "nothingToPublish";

export type UploadProblem =
  | CommonProblem
  | "tooLarge"
  | "infected"
  | "unsupported"
  | "empty"
  | "badName"
  | "tooMany"
  | "wrongType";

export interface Refusal<P extends string> {
  problem: P;
  /** Fields the API named (422 `invalid_teaser`, `cannot_publish`, `unknown_*`). */
  fields: FieldIssue[];
  /** The plan's cap on published ideas (402 `plan_limit`), when the API gave it. */
  limit?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function detail(body: unknown): Record<string, unknown> {
  return isRecord(body) && isRecord(body.detail) ? body.detail : {};
}

/** The `errors` list of a 422 (`[{field, code, message}]`), keeping the fields this screen knows. */
export function fieldIssues(body: unknown): FieldIssue[] {
  const errors = detail(body).errors;
  if (!Array.isArray(errors)) return [];
  const out: FieldIssue[] = [];
  for (const error of errors) {
    if (!isRecord(error) || typeof error.field !== "string" || typeof error.code !== "string") continue;
    if (isFieldName(error.field)) out.push({ field: error.field, code: error.code });
  }
  return out;
}

// A reference the API could not find belongs to one field.
const REFERENCE_FIELD: Record<string, FieldIssue> = {
  unknown_niche: { field: "niche_id", code: "unknown" },
  unknown_county: { field: "county_code", code: "unknown" },
  unknown_problem: { field: "problems", code: "unknown" },
};

function common(status: number, code: string | undefined): CommonProblem | null {
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  if (status === 404) return "notFound";
  if (status === 409 && code === "proposal_hidden") return "hidden";
  if (status === 503) return "unavailable";
  return null;
}

function fieldsRefusal<P extends string>(body: unknown, problem: P): Refusal<P> | null {
  const code = apiErrorCode(body);
  if (code && REFERENCE_FIELD[code]) return { problem, fields: [REFERENCE_FIELD[code]] };
  const fields = fieldIssues(body);
  return fields.length > 0 ? { problem, fields } : null;
}

/** A refused save (POST or PATCH of the draft). */
export function saveRefusal(status: number, body: unknown): Refusal<SaveProblem> {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return { problem: shared, fields: [] };
  if (status === 422) return fieldsRefusal<SaveProblem>(body, "fields") ?? { problem: "validation", fields: [] };
  return { problem: "failed", fields: [] };
}

/** A refused publish (POST /api/me/proposals/{id}/publish). */
export function publishRefusal(status: number, body: unknown): Refusal<PublishProblem> {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return { problem: shared, fields: [] };
  if (status === 403 && code === "d1_required") return { problem: "d1Required", fields: [] };
  if (status === 402) {
    const limit = detail(body).limit;
    return { problem: "planLimit", fields: [], limit: typeof limit === "number" ? limit : undefined };
  }
  if (status === 409 && code === "attestation_text_outdated") return { problem: "attestationsChanged", fields: [] };
  if (status === 409 && code === "nothing_to_publish") return { problem: "nothingToPublish", fields: [] };
  if (status === 422 && code === "attestations_required") return { problem: "attestationsRequired", fields: [] };
  if (status === 422) return fieldsRefusal<PublishProblem>(body, "fields") ?? { problem: "failed", fields: [] };
  return { problem: "failed", fields: [] };
}

const UPLOAD_CODES: Record<string, UploadProblem> = {
  too_large: "tooLarge",
  attachment_infected: "infected",
  unsupported_file: "unsupported",
  empty_file: "empty",
  invalid_file_name: "badName",
  too_many_attachments: "tooMany",
};

/** A refused attachment upload. */
export function uploadRefusal(status: number, body: unknown): Refusal<UploadProblem> {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return { problem: shared, fields: [] };
  if (status === 413) return { problem: "tooLarge", fields: [] };
  const known = code ? UPLOAD_CODES[code] : undefined;
  return { problem: known ?? "failed", fields: [] };
}
