import { publicProblem } from "@/lib/public/public-data";

import { noCard, shareCard } from "../../share-card";

/**
 * GET /og/problem/<id> (P24; REQ-UX-04): the share card of a public problem (GET /api/public/problems/{id}, public, so
 * a link preview's crawler gets it): its title and its niche (or county). Anything not public answers 404 with no image.
 */
export async function GET(_request: Request, ctx: RouteContext<"/og/problem/[id]">) {
  const read = await publicProblem((await ctx.params).id);
  if (read.kind !== "found") return noCard();
  const { problem } = read;
  return shareCard({ title: problem.title, line: problem.niche?.name ?? problem.county?.name ?? null });
}
