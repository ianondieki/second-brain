import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { DataTable } from "@/components/ui/DataTable";
import { first } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";

import { formatCalendarDate } from "@/lib/format";

import { AdminShell } from "../AdminShell";
import { StaffEyebrow } from "../StaffEyebrow";
import { QueueSummary, QueueSurface } from "../QueueSurface";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { ViewTabs } from "../ViewTabs";
import { ClaimRow } from "./ClaimRow";
import { CLAIM_VIEWS, claimView, claimViewHref, slaState, type Claim, type ClaimView } from "./claims";
import { getClaims } from "./data";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminClaims");
  return { title: t("pageTitle") };
}

/** Where each view's empty state sends the admin: to the other claims worth reading. */
const EMPTY_TO: Record<ClaimView, ClaimView> = { review: "in_progress", in_progress: "review", closed: "review" };

/**
 * Claims (REQ-DIR-03 queue, REQ-ADM-01; docs/spec/06 6.2 and 6.12): the organisation claims awaiting review, oldest
 * first, with the review time left as a mark and words; those still waiting for the claimant; and the closed ones.
 * Read only: the prototype decides no claim, so the screen has no primary action. Staff admins only; a stale second
 * factor asks for a fresh code first.
 */
export default async function ClaimsPage({ searchParams }: PageProps<"/admin/claims">) {
  const { role } = await staffContext();
  const view = claimView(first((await searchParams).view));
  const t = await getTranslations("adminClaims");
  const shell = (lead: ReactNode, children: ReactNode) => (
    <AdminShell role={role} current="claims" wide>
      <div className="flex max-w-5xl flex-col gap-8">
        <PageHero eyebrow={<StaffEyebrow section="claims" />} title={t("title")} lead={lead} focusable />
        {children}
      </div>
    </AdminShell>
  );
  const notAdmin = () =>
    shell(null, <EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href="/admin" />);
  if (role !== "admin") return notAdmin();

  const loaded = await getClaims(view);
  if (loaded.kind === "forbidden") return notAdmin();
  if (loaded.kind === "stepUp") {
    return shell(
      null,
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }

  const { items, reviewSlaDays } = loaded.data;
  const tabs = CLAIM_VIEWS.map((key) => ({ key, label: t(`tabs.${key}`), href: claimViewHref(key) }));
  return shell(
    t("lead", { days: reviewSlaDays }),
    <div>
      <ViewTabs label={t("tabsLabel")} tabs={tabs} current={view} />
      <div className="mt-6">
        {items.length > 0 ? (
          <QueueSurface raised={view === "review"} summary={view === "review" ? await reviewSummary(items) : undefined}>
            <DataTable
              aria-label={t(`list.${view}`)}
              columns={[t("columns.organisation"), t("columns.level"), t("columns.claimant"), t("columns.filed"), t("columns.status")]}
            >
              {items.map((claim) => (
                <ClaimRow key={claim.id} claim={claim} />
              ))}
            </DataTable>
          </QueueSurface>
        ) : (
          <EmptyState
            rule={false}
            sentence={t(`empty.${view}`)}
            action={t(`emptyAction.${view}`)}
            href={claimViewHref(EMPTY_TO[view])}
          />
        )}
      </div>
    </div>,
  );
}

/**
 * The review queue at a glance: how many claims wait, how many are due today or late, and the next day one falls due
 * (the review time is counted in Kenyan business days; the API gives each claim's last day).
 */
async function reviewSummary(items: readonly Claim[]) {
  const t = await getTranslations("adminClaims");
  const locale = await getLocale();
  const pressing = items.filter((claim) => {
    const sla = slaState(claim.sla);
    return sla !== null && sla.kind !== "due";
  }).length;
  const days = items.flatMap((claim) => (claim.sla ? [claim.sla.due_on] : [])).sort();
  return (
    <QueueSummary
      figures={[
        { key: "waiting", label: t("summary.waiting"), value: items.length },
        { key: "pressing", label: t("summary.pressing"), value: pressing },
        ...(days.length > 0 ? [{ key: "next", label: t("summary.next"), value: formatCalendarDate(locale, days[0]) }] : []),
      ]}
    />
  );
}
