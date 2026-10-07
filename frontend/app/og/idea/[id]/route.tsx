import { forwardHeaders, serverApi } from "@/lib/api/server";

import { noCard, shareCard } from "../../share-card";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * GET /og/idea/<id> (P24; REQ-UX-04): the share card of a published teaser (GET /api/proposals/{id}, Tier 1 only:
 * the public title and the niche). A draft, a held or hidden idea and an unknown id answer 404 with no image, as the
 * API does. The API reads teasers for a signed-in session, so the request's session is forwarded.
 */
export async function GET(_request: Request, ctx: RouteContext<"/og/idea/[id]">) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return noCard();
  try {
    const { data } = await serverApi().GET("/api/proposals/{proposal_id}", {
      params: { path: { proposal_id: id } },
      headers: await forwardHeaders(),
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
    });
    const title = data?.teaser.title?.trim();
    if (!title) return noCard();
    return await shareCard({ title, line: data!.teaser.niche?.label ?? null });
  } catch {
    return noCard();
  }
}
