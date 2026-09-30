import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";

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
 * One claim in the queue (REQ-DIR-03 queue): the organisation (the way into the claim; by id when staff cannot read
 * it), one tag (the review time left, or the status), what it asks for, who filed it, the domain and when. No
 * registration number, KRA PIN or address here: those are on the claim's own page only.
 */
export async function ClaimRow({ claim }: { claim: Claim }) {
  const t = await getTranslations("adminClaims");
  const locale = await getLocale();
  const name = orgName(claim.org);
  return (
    <li data-claim={claim.id} className="border-t border-line py-5 first:border-t-0 first:pt-0">
      <h3 className="text-lg text-ink">
        <Link
          href={claimHref(claim.id)}
          data-claim-link=""
          className="inline-flex min-h-11 items-center font-semibold [overflow-wrap:anywhere] text-ink underline decoration-line decoration-1 underline-offset-4 hover:text-jacaranda hover:decoration-jacaranda"
        >
          {name ?? t("unnamed", { id: shortId(claim.org.id) })}
        </Link>
      </h3>
      {name ? null : <p className="max-w-[60ch] text-sm text-ink-soft">{t("unnamedNote")}</p>}
      <ul className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
        <li>
          <ClaimChip claim={claim} />
        </li>
        <li className="font-medium text-ink">{t(`level.${claim.level}`)}</li>
        <li>{t("by", { name: claim.claimant.display_name })}</li>
        <li className="[overflow-wrap:anywhere]">{claim.domain}</li>
        <li>{t("filed", { date: formatMoment(locale, claim.created_at) })}</li>
      </ul>
    </li>
  );
}
