import { getTranslations } from "next-intl/server";

import { normaliseCertId } from "@/app/(public)/verify/certificate";
import { lookupCertificate } from "@/app/(public)/verify/lookup";

import { noCard, shareCard } from "../../share-card";

/**
 * GET /og/verify/<certificate id> (P24; REQ-UX-04): the share card of a certificate: its id and "Registered on Wazo",
 * for a certificate the public check finds (GET /api/verify/{cert_id}); anything else answers 404 with no image.
 */
export async function GET(_request: Request, ctx: RouteContext<"/og/verify/[id]">) {
  const certId = normaliseCertId((await ctx.params).id);
  if (!certId) return noCard();
  const lookup = await lookupCertificate(certId);
  if (lookup.kind !== "found") return noCard();
  const t = await getTranslations("og");
  return shareCard({ title: certId, line: t("registered"), code: true });
}
