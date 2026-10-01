import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { DataTable } from "@/components/ui/DataTable";
import { first } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";

import { AdminShell } from "../AdminShell";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { ViewTabs } from "../ViewTabs";
import { ClaimRow } from "./ClaimRow";
import { CLAIM_VIEWS, claimView, claimViewHref, type ClaimView } from "./claims";
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
        <PageHeader title={t("title")} lead={lead} focusable />
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
          <DataTable
            aria-label={t(`list.${view}`)}
            columns={[t("columns.organisation"), t("columns.level"), t("columns.claimant"), t("columns.filed"), t("columns.status")]}
          >
            {items.map((claim) => (
              <ClaimRow key={claim.id} claim={claim} />
            ))}
          </DataTable>
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
