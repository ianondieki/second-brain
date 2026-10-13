import { unstable_rethrow } from "next/navigation";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass, textLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { DownloadIcon } from "@/components/ui/icons";
import { forwardHeaders, serverApi } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";
import { billingHref } from "@/lib/billing/upgrade";

// "Export CSV" on the organisation's Engagements list (REQ-ENG-17; docs/platform/tasks/P28.md track D; docs/spec/05
// entitlements: `csv_export`). The plan is read the way Plan & billing reads it (GET /api/orgs/{org_id}/entitlements):
// with the entitlement, a plain download link to the API (same origin through the /api rewrite, so the session cookie
// goes with it and no script is needed); without it, one muted line naming the plan that has it, linking to billing.

type Plan = components["schemas"]["PlanOut"];

const TIMEOUT_MS = 5000;
const CSV_EXPORT = "csv_export";

/** Only an explicit `true` grants a feature (backend entitlements.py `allows`). */
export function allowsCsv(limits: Record<string, unknown> | null | undefined): boolean {
  return limits?.[CSV_EXPORT] === true;
}

/** The plan to name when the organisation's has no CSV export: the first one on sale that has it, else any that has. */
export function csvPlan(plans: readonly Pick<Plan, "name" | "purchasable" | "limits">[]): string | null {
  const having = plans.filter((plan) => allowsCsv(plan.limits as Record<string, unknown>));
  return (having.find((plan) => plan.purchasable) ?? having[0])?.name ?? null;
}

/** The address the link downloads (the API's export, through the same-origin /api rewrite). */
export function csvHref(orgId: string): string {
  return `/api/orgs/${encodeURIComponent(orgId)}/engagements.csv`;
}

async function read<T>(call: () => Promise<{ data?: T }>): Promise<T | null> {
  try {
    return (await call()).data ?? null;
  } catch (error) {
    unstable_rethrow(error);
    return null;
  }
}

/**
 * The link or the line, under the list's filter. Nothing when the plan cannot be read in time: the list never waits
 * on it or says something it does not know.
 */
export async function CsvExport({ orgId, className }: { orgId: string; className?: string }) {
  const options = async () => ({
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(TIMEOUT_MS),
    cache: "no-store" as const,
  });
  const entitlements = await read(async () =>
    serverApi().GET("/api/orgs/{org_id}/entitlements", { params: { path: { org_id: orgId } }, ...(await options()) }),
  );
  if (!entitlements) return null;
  const t = await getTranslations("engagements");
  if (allowsCsv(entitlements.limits)) {
    return (
      <a
        href={csvHref(orgId)}
        download
        className={cn(standaloneLinkClass, "gap-2 no-underline hover:underline", className)}
        data-csv-export=""
      >
        <DownloadIcon className="size-5 shrink-0" />
        {t("exportCsv")}
      </a>
    );
  }
  const plans = await read(async () =>
    serverApi().GET("/api/plans", { params: { query: { side: "org" } }, ...(await options()) }),
  );
  const plan = plans ? csvPlan(plans.plans) : null;
  const link = (chunks: ReactNode) => (
    <a href={billingHref(orgId)} className={textLinkClass}>
      {chunks}
    </a>
  );
  return (
    <p className={cn("max-w-[48ch] text-sm text-ink-soft", className)} data-csv-off={plan ?? ""}>
      {plan ? t.rich("csvOff", { plan, link }) : t.rich("csvOffUnknown", { link })}
    </p>
  );
}
