import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { SignedInShell } from "@/components/SignedInShell";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { CheckIcon } from "@/components/ui/status-icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { upgradeHref } from "@/lib/billing/upgrade";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Row, RowList } from "@/components/ui/RowList";
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
    <SignedInShell homeHref={home}>
      <PageHeader title={t("pageTitle")}>{lead}</PageHeader>
      <div className="mt-10">{children}</div>
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
      <RowList ordered data-ladder="">
        {plans.map((plan, index) => (
          <PlanRow
            key={plan.code}
            plan={plan}
            action={rowAction(plans, current.code, plan)}
            sameAs={sameAs[index]}
            href={upgradeHref(plan.code, { org: orgId })}
          />
        ))}
      </RowList>
    </Section>,
  );
}

/**
 * One plan of the ladder, a Row: its name, its price on the right (tabular figures) or "not sold here" under the name,
 * "Your plan" as the accent Badge on the current one (you are here), what the plan allows, and its action: the
 * primary "Upgrade to" on the plan a 402 would point to, the same words as a link on other plans that can be bought
 * (the checkout page is titled that way too).
 */
async function PlanRow({
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
    <Row
      aria-current={current ? "true" : undefined}
      data-plan={plan.code}
      title={plan.name}
      // A free plan's name already says so ("Free", "Claimed (Free)"); a plan not sold here says why under its name.
      // The price is the row's figure from 640 px; below that it is the meta line, so what the plan allows and its
      // one action keep the whole width at 360 px (ux-review round 2).
      figure={kind === "free" || kind === "notSold" ? undefined : price}
      figureFrom="sm"
      meta={
        kind === "notSold" ? price : kind === "free" ? undefined : <span className="text-base text-ink sm:hidden">{price}</span>
      }
      badges={
        current
          ? [
              <Badge key="yours" tone="accent" icon={<CheckIcon />} data-your-plan="">
                {t("yourPlan")}
              </Badge>,
            ]
          : undefined
      }
    >
      {lines.length > 0 ? (
        <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 text-ink-soft marker:text-ink-soft">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {action === "upgrade" ? (
        <div className="mt-3">
          <ButtonLink href={href} variant="primary" className="no-underline">
            {t("upgradeTo", { plan: plan.name })}
          </ButtonLink>
        </div>
      ) : action === "choose" ? (
        <p className="mt-1">
          <StandaloneLink href={href}>{t("upgradeTo", { plan: plan.name })}</StandaloneLink>
        </p>
      ) : null}
    </Row>
  );
}
