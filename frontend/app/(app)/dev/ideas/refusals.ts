import { apiErrorCode } from "@/lib/api/error-code";
import { upgradePlanOf } from "@/lib/billing/upgrade";

import { common, detail, fieldsRefusal, type PublishProblem, type Refusal, type UploadProblem } from "./outcomes";

// Publish and upload refusals, apart from the save path's (outcomes.ts), which the editor loads with its first save.

/** A refused publish (POST /api/me/proposals/{id}/publish). */
export function publishRefusal(status: number, body: unknown): Refusal<PublishProblem> {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return { problem: shared, fields: [] };
  if (status === 403 && code === "d1_required") return { problem: "d1Required", fields: [] };
  if (status === 402) {
    const limit = detail(body).limit;
    const upgrade = upgradePlanOf(body) ?? undefined;
    return { problem: "planLimit", fields: [], limit: typeof limit === "number" ? limit : undefined, upgrade };
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
