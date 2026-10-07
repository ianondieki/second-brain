import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell } from "@/components/SignedInShell";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { cn } from "@/components/ui/cn";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { CheckIcon } from "@/components/ui/status-icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { upgradeHref } from "@/lib/billing/upgrade";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";

import { getCurrentPlan, getPlans } from "./data";
import { SamplePrices } from "./SamplePrices";
import { billingSubject, priceKind, rowAction, sameLinesAs, sideOf, type Plan, type RowAction } from "./plans";
import { lineTexts, priceText } from "./text";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

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
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide>
      <div className="max-w-4xl">
        <PageHeader title={t("pageTitle")}>{lead}</PageHeader>
        <div className="mt-10">{children}</div>
      </div>
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
      <p className="mt-2 [overflow-wrap:anywhere] text-ink-soft">{t("forOrg", { org: subject.membership.org_name })}</p>
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
  const sameAs = sameLinesAs(plans);
  const currentName = plans.find((p) => p.code === current.code)?.name ?? current.code;
  return shell(
    <>
      {forOrg}
      <p className="mt-3 text-ink" data-current-plan={current.code}>
        {t("current", { plan: currentName })}
      </p>
    </>,
    <Section
      title={t("plansTitle")}
      headingId="plans-title"
      description={catalogue.sample_prices ? <SamplePrices label={t("samplePrices")} /> : undefined}
    >
      {/* The ladder: one column on phones; from 1024 px two or three across, whichever leaves no plan alone in a row. */}
      <ol data-ladder="" className={cn("grid grid-cols-1 gap-4", plans.length === 3 || plans.length > 4 ? "lg:grid-cols-3" : "lg:grid-cols-2")}>
        {plans.map((plan, index) => (
          <PlanCard
            key={plan.code}
            plan={plan}
            action={rowAction(plans, current.code, plan)}
            sameAs={sameAs[index]}
            href={upgradeHref(plan.code, { org: orgId })}
          />
        ))}
      </ol>
    </Section>,
  );
}

/**
 * One plan of the ladder, a card (D-52): its name, its price (tabular figures) or "not sold here" under the name,
 * "Your plan" as the accent Badge on the current one (you are here, with the accent border), what the plan allows,
 * and its action: the primary "Upgrade to" on the plan a 402 would point to, the same words as a link on other plans
 * that can be bought (the checkout page is titled that way too).
 */
async function PlanCard({
  plan,
  action,
  href,
  sameAs,
}: {
  plan: Plan;
  action: RowAction;
  href: string;
  /** An earlier plan that allows the same: said once instead of repeating its list. */
  sameAs: string | null;
}) {
  const t = await getTranslations("billing");
  const [price, listed] = await Promise.all([priceText(plan), lineTexts(plan)]);
  const lines = sameAs ? [t("sameAs", { plan: sameAs })] : listed;
  const kind = priceKind(plan);
  const current = action === "current";
  return (
    <Card
      as="li"
      // The plan to move to is raised; the current one carries a bloom ring ("you are here"; a ring, so the card's
      // own hairline needs no override); the rest are flat.
      variant={action === "upgrade" ? "raised" : "flat"}
      aria-current={current ? "true" : undefined}
      data-plan={plan.code}
      className={cn("flex flex-col gap-3", current && "ring-2 ring-accent")}
    >
      {/* The name, then the price as the card's figure in the display face (P20), then "Your plan". */}
      <div className="flex flex-col gap-1">
        <h3 className="text-base text-ink">{plan.name}</h3>
        {kind === "free" ? null : (
          <p
            className={cn(
              "tabular-nums",
              kind === "notSold" ? "text-sm text-ink-soft" : "font-figure text-xl font-[680] tracking-[-0.02em] text-ink",
            )}
          >
            {price}
          </p>
        )}
      </div>
      {current ? (
        <p>
          <Badge tone="accent" icon={<CheckIcon />} data-your-plan="">
            {t("yourPlan")}
          </Badge>
        </p>
      ) : null}
      {lines.length > 0 ? (
        <ul className="flex flex-col gap-1 text-ink-soft">
          {lines.map((line) => (
            <li key={line} className="flex gap-2">
              <CheckIcon className="mt-1 size-4 shrink-0 text-accent" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {action === "upgrade" ? (
        <div className="mt-auto pt-2">
          <ButtonLink href={href} variant="primary" className="no-underline">
            {t("upgradeTo", { plan: plan.name })}
          </ButtonLink>
        </div>
      ) : action === "choose" ? (
        <p className="mt-auto">
          <StandaloneLink href={href}>{t("upgradeTo", { plan: plan.name })}</StandaloneLink>
        </p>
      ) : null}
    </Card>
  );
}
