import type { components } from "@/lib/api/schema";
import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode, detailOf } from "@/lib/api/error-code";

// The prior-knowledge declaration from the browser (REQ-PROV-06): POST …/prior-knowledge with the evidence's
// fingerprint, title and date (never the file). Each settles into the recorded declaration or a refusal the sheet
// words from its own strings (`declarationSheet.refusal.*`). Loaded with the sheet.

export type Declaration = components["schemas"]["DeclarationOut"];
export type DeclarationInput = components["schemas"]["DeclarationBody"];

export type DeclarationRefusal =
  | "noTier2"
  | "windowClosed"
  | "alreadyDeclared"
  | "ended"
  | "notAllowed"
  | "invalidTitle"
  | "future"
  | "afterView"
  | "invalidHash"
  | "notFound"
  | "network"
  | "generic";

const BY_CODE: Record<string, DeclarationRefusal> = {
  no_tier2_access_yet: "noTier2",
  declaration_window_closed: "windowClosed",
  already_declared: "alreadyDeclared",
  engagement_ended: "ended",
  role_not_allowed: "notAllowed",
  invalid_evidence_title: "invalidTitle",
  evidence_date_in_future: "future",
  evidence_after_first_view: "afterView",
};

export function declarationRefusal(status: number, error: unknown): DeclarationRefusal {
  const code = apiErrorCode(error);
  if (code && code in BY_CODE) return BY_CODE[code];
  // A request-validation error names its field: the hash, the title or the date.
  if (
    code === "validation" &&
    error &&
    typeof error === "object" &&
    Array.isArray((error as { detail?: unknown }).detail)
  ) {
    const fields = ((error as { detail: Array<{ loc?: unknown[] }> }).detail ?? []).flatMap((item) => item.loc ?? []);
    if (fields.includes("evidence_sha256_hex")) return "invalidHash";
    if (fields.includes("evidence_title")) return "invalidTitle";
    if (fields.includes("evidence_dated_on")) return "future";
  }
  if (status === 404) return "notFound";
  if (status === 403) return "notAllowed";
  return "generic";
}

export type DeclarationOutcome =
  | { ok: true; declaration: Declaration }
  | { ok: false; refusal: DeclarationRefusal; closedOn?: string };

export async function declare(
  orgId: string,
  engagementId: string,
  input: DeclarationInput,
  client: ApiClient = api,
): Promise<DeclarationOutcome> {
  try {
    const { data, error, response } = await client.POST(
      "/api/orgs/{org_id}/engagements/{engagement_id}/prior-knowledge",
      {
        params: { path: { org_id: orgId, engagement_id: engagementId } },
        body: input,
      },
    );
    if (data) return { ok: true, declaration: data };
    const closed = detailOf(error)?.window_closed_on;
    return {
      ok: false,
      refusal: declarationRefusal(response.status, error),
      ...(typeof closed === "string" ? { closedOn: closed } : {}),
    };
  } catch {
    return { ok: false, refusal: "network" };
  }
}
