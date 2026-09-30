import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { SignedInShell } from "@/components/SignedInShell";
import { buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon } from "@/components/ui/status-icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { upgradeHref } from "@/lib/billing/upgrade";

import { EmptyState } from "../org/EmptyState";
import { getCurrentPlan, getPlans } from "./data";
import { SamplePrices } from "./SamplePrices";
import { billingSubject, priceKind, rowAction, sideOf, type Plan, type RowAction } from "./plans";
import { lineTexts, priceText } from "./text";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("billing");
  return { title: t("pageTitle") };
}

/**
 * Plan & billing (REQ-BIL-08; docs/spec/05, docs/spec/07 item 1 avatar menu): the developer's plan, or an
 * organisation's for its owner, admin or finance member (`?org=`). The ladder from GET /api/plans in plans.yaml order,
 * each plan with its price and what it allows in plain words, the current plan marked, and the next plan up as the
 * screen's one primary action. Prices carry "Sample prices, not final" while plans.yaml is a placeholder (D-44).
 */
export default async function BillingPage({ searchParams }: PageProps<"/billing">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  const t = await getTranslations("billing");
  const subject = billingSubject(me, (await searchParams).org);

  const shell = (lead: ReactNode, children: ReactNode) => (
    <SignedInShell homeHref={home}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
      {lead}
      <div className="mt-8">{children}</div>
    </SignedInShell>
  );

  if (subject.kind === "notMember") {
    return shell(null, <EmptyState sentence={t("refused.notMember")} action={t("action.billing")} href="/billing" />);
  }
  if (subject.kind === "noOrg") {
    return shell(null, <EmptyState sentence={t("refused.noOrg")} action={t("action.home")} href={home} />);
  }
  if (subject.kind === "notPayer") {
    const org = subject.membership.org_name;
    return shell(null, <EmptyState sentence={t("refused.notPayer", { org })} action={t("action.home")} href={home} />);
  }

  const orgId = subject.kind === "org" ? subject.membership.org_id : undefined;
  const forOrg =
    subject.kind === "org" ? (
      <p className="mt-1 [overflow-wrap:anywhere] text-ink-soft">{t("forOrg", { org: subject.membership.org_name })}</p>
    ) : null;
  const [catalogue, current] = await Promise.all([getPlans(sideOf(subject)), getCurrentPlan(subject)]);

  if (current.kind === "refused") {
    const org = subject.kind === "org" ? subject.membership.org_name : "";
    return current.refusal === "mfaSetup"
      ? shell(
          forOrg,
          <EmptyState
            sentence={t("refused.mfaSetup", { org })}
            action={t("action.turnOnMfa")}
            href="/settings/security"
            primary
          />,
        )
      : shell(
          forOrg,
          <EmptyState sentence={t("refused.mfaRequired", { org })} action={t("action.enterCode")} href="/auth/mfa" />,
        );
  }

  const plans = catalogue.plans;
  const currentName = plans.find((p) => p.code === current.code)?.name ?? current.code;
  return shell(
    <>
      {forOrg}
      <p className="mt-3 text-ink" data-current-plan={current.code}>
        {t("current", { plan: currentName })}
      </p>
    </>,
    <section aria-labelledby="plans-title">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line pb-3">
        <h2 id="plans-title" className="text-lg text-ink">
          {t("plansTitle")}
        </h2>
        {catalogue.sample_prices ? <SamplePrices label={t("samplePrices")} /> : null}
      </div>
      <ol className="mt-6 flex flex-col" data-ladder="">
        {plans.map((plan, index) => (
          <PlanRow
            key={plan.code}
            plan={plan}
            action={rowAction(plans, current.code, plan)}
            last={index === plans.length - 1}
            href={upgradeHref(plan.code, { org: orgId })}
          />
        ))}
      </ol>
    </section>,
  );
}

/**
 * One rung of the ladder: a mark on the rail (filled for the current plan), the name and price, what the plan allows,
 * and its action. Only the upgrade the API's 402 would point to is the primary button.
 */
async function PlanRow({ plan, action, last, href }: { plan: Plan; action: RowAction; last: boolean; href: string }) {
  const t = await getTranslations("billing");
  const [price, lines] = await Promise.all([priceText(plan), lineTexts(plan)]);
  const current = action === "current";
  const reachable = action === "upgrade" || action === "choose";
  return (
    <li
      aria-current={current ? "true" : undefined}
      data-plan={plan.code}
      className="relative flex gap-4 pb-8 last:pb-0"
    >
      {last ? null : <span aria-hidden="true" className="absolute top-7 bottom-1 left-[11px] w-0.5 rounded-full bg-line" />}
      <span
        aria-hidden="true"
        className={cn(
          "relative mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border-2",
          current
            ? "border-jacaranda bg-jacaranda text-on-accent"
            : reachable
              ? "border-jacaranda bg-paper"
              : "border-line bg-paper",
        )}
      >
        {current ? <CheckIcon className="size-4" /> : null}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4">
          <h3 className="text-lg leading-7 [overflow-wrap:anywhere] text-ink">
            {plan.name}
          </h3>
          <p className={cn("tabular-nums", priceKind(plan) === "notSold" ? "text-sm text-ink-soft" : "text-ink")}>
            {price}
          </p>
        </div>
        {current ? (
          <p className="mt-0.5 flex items-center gap-1.5 text-sm font-semibold text-jacaranda" data-your-plan="">
            <CheckIcon className="size-4 shrink-0" />
            {t("yourPlan")}
          </p>
        ) : null}
        {lines.length > 0 ? (
          <ul className="mt-2 flex flex-col gap-1 text-ink-soft">
            {lines.map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden="true" className="mt-[0.7em] size-1 shrink-0 rounded-full bg-ink-soft" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : null}
        {action === "upgrade" ? (
          <Link href={href} data-primary="" className={buttonClass("primary", "mt-4 no-underline")}>
            {t("upgradeTo", { plan: plan.name })}
          </Link>
        ) : action === "choose" ? (
          <Link href={href} className={cn(standaloneLinkClass, "mt-2")}>
            {t("choose", { plan: plan.name })}
          </Link>
        ) : null}
      </div>
    </li>
  );
}

