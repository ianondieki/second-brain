import { getLocale, getTranslations } from "next-intl/server";

import { formatMoment } from "@/components/problem/problem";
import { Chip } from "@/components/tracker/Chip";
import Link from "next/link";

import { DataCell, DataRow, dataLinkClass } from "@/components/ui/DataTable";

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
 * One claim in the queue (REQ-DIR-03 queue), a row of the queue's table: the organisation (the way into the claim, the
 * row header; by id when staff cannot read it), the level, who filed it, the domain, when, and one status badge (the
 * review time left, or the status). No registration number, KRA PIN or address here: those are on the claim's own
 * page only.
 */
export async function ClaimRow({ claim }: { claim: Claim }) {
  const t = await getTranslations("adminClaims");
  const locale = await getLocale();
  const name = orgName(claim.org);
  return (
    <DataRow data-claim={claim.id}>
      <DataCell head label={t("columns.organisation")} className="sm:w-[26%]">
        <Link href={claimHref(claim.id)} data-claim-link="" className={dataLinkClass}>
          {name ?? t("unnamed", { id: shortId(claim.org.id) })}
        </Link>
        {name ? null : <p className="mt-1 max-w-[40ch] text-sm text-ink-soft">{t("unnamedNote")}</p>}
      </DataCell>
      <DataCell label={t("columns.level")} className="sm:w-[24%]">
        <span className="font-medium text-ink">{t(`level.${claim.level}`)}</span>
      </DataCell>
      <DataCell label={t("columns.claimant")} className="sm:w-[22%]">
        {claim.claimant.display_name}
        <span className="block text-sm break-words text-ink-soft">{claim.domain}</span>
      </DataCell>
      <DataCell label={t("columns.filed")} figure nowrap className="text-ink-soft">
        {formatMoment(locale, claim.created_at)}
      </DataCell>
      <DataCell label={t("columns.status")} nowrap>
        {await ClaimChip({ claim })}
      </DataCell>
    </DataRow>
  );
}
