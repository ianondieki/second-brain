import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import { Row } from "@/components/ui/RowList";

import { claimHref, orgName, shortId, slaChip, slaState, STATUS_CHIP, type Claim } from "./claims";

/**
 * A claim's state as one tag, a mark and words (docs/spec/07 item 6): the review time left for a claim awaiting
 * review ("Due in 2 business days", "Due today", "Overdue"), else its status.
 */
export async function ClaimChip({ claim }: { claim: Pick<Claim, "status" | "sla"> }) {
  const t = await getTranslations("adminClaims");
  const sla = slaState(claim.sla);
  if (!sla) return <Chip kind={STATUS_CHIP[claim.status]}>{t(`status.${claim.status}`)}</Chip>;
  const text =
    sla.kind === "overdue"
      ? t("sla.overdue")
      : sla.kind === "today"
        ? t("sla.today")
        : t("sla.due", { days: sla.days });
  return (
    <span data-sla={sla.kind}>
      <Chip kind={slaChip(sla)}>{text}</Chip>
    </span>
  );
}

/**
 * One claim in the queue (REQ-DIR-03 queue), a Row: the organisation (the way into the claim, an h2 under the page's
 * h1; by id when staff cannot read it), one status badge (the review time left, or the status), then what it asks
 * for, who filed it, the domain and when as the meta line. No registration number, KRA PIN or address here: those
 * are on the claim's own page only.
 */
export async function ClaimRow({ claim }: { claim: Claim }) {
  const t = await getTranslations("adminClaims");
  const locale = await getLocale();
  const name = orgName(claim.org);
  return (
    <Row
      data-claim={claim.id}
      data-claim-link=""
      headingLevel={2}
      title={name ?? t("unnamed", { id: shortId(claim.org.id) })}
      href={claimHref(claim.id)}
      meta={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span className="font-medium text-ink">{t(`level.${claim.level}`)}</span>
          <span>{t("by", { name: claim.claimant.display_name })}</span>
          <span className="[overflow-wrap:anywhere]">{claim.domain}</span>
          <span>{t("filed", { date: formatMoment(locale, claim.created_at) })}</span>
        </span>
      }
      badges={[await ClaimChip({ claim })]}
    >
      {name ? null : <p className="max-w-[60ch] text-sm text-ink-soft">{t("unnamedNote")}</p>}
    </Row>
  );
}
