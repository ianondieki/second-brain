import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { billingHref, upgradeHref } from "@/lib/billing/upgrade";

import { planFull, type BriefPlan, type PlanOption } from "../briefs";

/**
 * What the plan allows, said once (REQ-DIR-05; docs/spec/05): a quiet line while there is room ("Open Briefs on your
 * plan: 1 of 5"); when every open Brief is in use, one notice naming the next plan up with its one upgrade link (none
 * at the top of the ladder). The Problems list and the form's page both show this, never a second copy.
 */
export async function PlanNotice({
  plan,
  next,
  orgId,
  here,
  plansUnknown = false,
}: {
  plan: BriefPlan;
  /** The plan to buy for more open Briefs (briefUpgrade), or null. */
  next: PlanOption | null;
  orgId: string;
  /** The page the checkout comes back to. */
  here: string;
  /** The plans could not be read: the next plan is unknown, never "none" (the top of the ladder). */
  plansUnknown?: boolean;
}) {
  const t = await getTranslations("briefs");
  if (!planFull(plan)) {
    return (
      <p className="mt-6 text-sm text-ink" data-plan-cap={plan.problem_briefs ?? "unlimited"}>
        {plan.problem_briefs === null ? t("capUnlimited") : t("cap", { used: plan.used, limit: plan.problem_briefs })}
      </p>
    );
  }
  const counts = { used: plan.used, limit: plan.problem_briefs ?? plan.used };
  if (plansUnknown) {
    return (
      <Callout className="mt-6 max-w-[62ch]" data-plan-full="unknown">
        <p>{t("capFullUnknown", counts)}</p>
        <Link href={billingHref(orgId)} className={standaloneLinkClass} data-billing="">
          {t("billing")}
        </Link>
      </Callout>
    );
  }
  return (
    <Callout className="mt-6 max-w-[62ch]" data-plan-full="">
      <p>{next ? t("capFull", { ...counts, plan: next.name }) : t("capFullTop", counts)}</p>
      {next ? (
        <Link href={upgradeHref(next.code, { org: orgId, next: here })} className={standaloneLinkClass} data-upgrade="">
          {t("upgradeTo", { plan: next.name })}
        </Link>
      ) : null}
    </Callout>
  );
}
