import { redirect } from "next/navigation";

import { apiErrorCode } from "@/lib/api/error-code";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { Plans, PlanSide, Subject } from "./plans";

// Server-side reads for Plan & billing, each bounded so a hung API ends in the route's error page. The session cookie
// is forwarded; the organisation is always one the person pays for (plans.ts billingSubject).

const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/** The plan ladder of one side (public: prices and limits are not personal). */
export async function getPlans(side: PlanSide): Promise<Plans> {
  const { data, response } = await serverApi().GET("/api/plans", { params: { query: { side } }, ...(await options()) });
  if (!data) throw new Error(`GET /api/plans answered ${response.status}`);
  return data;
}

/** The subject's live plan code, or why the organisation's cannot be read yet (its second-factor rules). */
export type Current = { kind: "plan"; code: string } | { kind: "refused"; refusal: "mfaRequired" | "mfaSetup" };

export async function getCurrentPlan(subject: Extract<Subject, { kind: "developer" | "org" }>): Promise<Current> {
  const { data, error, response } =
    subject.kind === "org"
      ? await serverApi().GET("/api/orgs/{org_id}/entitlements", {
          params: { path: { org_id: subject.membership.org_id } },
          ...(await options()),
        })
      : await serverApi().GET("/api/me/entitlements", await options());
  if (data) return { kind: "plan", code: data.plan };
  const code = apiErrorCode(error);
  if (response.status === 401 && code === "mfa_required") return { kind: "refused", refusal: "mfaRequired" };
  if (response.status === 403 && code === "mfa_enrolment_required") return { kind: "refused", refusal: "mfaSetup" };
  if (response.status === 401) redirect("/login"); // the session ended between the page's /me check and this call
  throw new Error(`GET entitlements answered ${response.status}`);
}
