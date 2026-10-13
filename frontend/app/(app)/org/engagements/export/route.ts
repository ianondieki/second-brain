import { NextResponse, type NextRequest } from "next/server";

import { apiErrorCode } from "@/lib/api/error-code";
import { forwardHeaders, serverApi } from "@/lib/api/server";
import { retryAfterSeconds } from "@/lib/retry-after";

import { exportOutcome, exportRefusalHref, type ExportRefusal } from "./outcome";

/** Headers of the API's file passed on to the browser as they are (the download's name, its type, the truncation mark). */
const PASSED = ["Content-Type", "Content-Disposition", "X-Export-Truncated"] as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * "Export CSV" (REQ-ENG-17; the P28 review's MAJOR 7): GET /org/engagements/export?org=<id> asks the API for the
 * organisation's CSV with the person's session (the session cookie and the visitor's address, as every server read),
 * and streams it on a 200 as a download (Content-Disposition kept, never cached; a truncated export still downloads and
 * carries X-Export-Truncated). Any other answer sends the browser back to the Engagements list with ?export=<why>,
 * where one server-rendered sentence says it (no script): the plan, too many exports for now (and roughly when), the
 * session ended, or not found. Signed out, the proxy sends a visit here to /login first, as for any /org page.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const org = request.nextUrl.searchParams.get("org") ?? "";
  const back = (refusal: ExportRefusal, retryAfter?: number | null) =>
    NextResponse.redirect(new URL(exportRefusalHref(refusal, UUID.test(org) ? org : null, retryAfter), request.url), 303);
  if (!UUID.test(org)) return back("notFound");
  let answer: { data?: ReadableStream<Uint8Array> | null; error?: unknown; response: Response };
  try {
    answer = await serverApi().GET("/api/orgs/{org_id}/engagements.csv", {
      params: { path: { org_id: org } },
      headers: await forwardHeaders(),
      parseAs: "stream",
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return back("failed");
  }
  const { data, error, response } = answer;
  if (response.status === 200 && data) {
    const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of PASSED) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(data, { status: 200, headers });
  }
  const refusal = exportOutcome(response.status, apiErrorCode(error));
  return back(refusal, refusal === "rateLimited" ? retryAfterSeconds(response.headers.get("Retry-After")) : null);
}
