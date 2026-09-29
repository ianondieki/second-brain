import { forwardHeaders, serverApi } from "@/lib/api/server";

import type { CertificateCheck } from "./certificate";

export type Lookup =
  | { kind: "found"; record: CertificateCheck }
  | { kind: "notFound" }
  | { kind: "rateLimited" }
  | { kind: "unavailable" };

/**
 * GET /api/verify/{cert_id} for a normalised id, settled into what the page shows. Public: no session cookie is
 * sent, only the visitor's forwarded address (the API limits lookups per address). Bounded, so a slow API ends in
 * "try again", not a page that never renders.
 */
export async function lookupCertificate(certId: string): Promise<Lookup> {
  try {
    const { data, response } = await serverApi().GET("/api/verify/{cert_id}", {
      params: { path: { cert_id: certId } },
      headers: await forwardHeaders({ session: false }),
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
    });
    if (data) return { kind: "found", record: data };
    if (response.status === 404 || response.status === 422) return { kind: "notFound" };
    if (response.status === 429) return { kind: "rateLimited" };
    return { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}
