import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { InfoIcon } from "@/components/ui/status-icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { billingHref, isOrgId, isPlanCode, safeNext } from "@/lib/billing/upgrade";
import { clientStrings } from "@/lib/i18n/client-strings";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { BackLink } from "@/components/ui/BackLink";
import { getCurrentPlan, getPlans, planName } from "../data";
import { billingSubject, sideOf } from "../plans";
import { SamplePrices } from "../SamplePrices";
import { lineTexts, priceText } from "../text";
import { Checkout } from "./Checkout";

type Search = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value);

export async function generateMetadata({ searchParams }: PageProps<"/billing/upgrade">): Promise<Metadata> {
  const t = await getTranslations("billing");
  const tc = await getTranslations("checkout");
  const code = one((await searchParams).plan);
  const name = isPlanCode(code) ? await planName(code) : null;
  return { title: name ? tc("pageTitle", { plan: name }) : t("pageTitle") };
}

/**
 * Upgrade to a plan (REQ-BIL-08; docs/spec/05): `?plan=<code>` from the ladder or a 402, `&org=` for an organisation,
 * `&next=` the page to go back to once paid, `&checkout=` a checkout in progress (after a reload). The plan must be one
 * of the subject's side that can be bought here; the steps themselves are the client's (Checkout.tsx).
 */
export default async function UpgradePage({ searchParams }: PageProps<"/billing/upgrade">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  const search: Search = await searchParams;
  const t = await getTranslations("billing");
  const tc = await getTranslations("checkout");
  const subject = billingSubject(me, search.org);
  const orgId = subject.kind === "org" ? subject.membership.org_id : undefined;
  const back = billingHref(orgId);

  // The back link is left out where the body is an empty state (its one action is the way on), and hidden by CSS
  // while the checkout shows a refusal that carries its own action ([data-checkout-blocked]).
  const shell = (title: string, children: ReactNode, tag?: ReactNode, withBack = true) => (
    <SignedInShell homeHref={home}>
      {withBack ? (
        <BackLink href={back} className="[main:has([data-checkout-blocked])_&]:hidden" data-page-back="">
          {tc("back")}
        </BackLink>
      ) : null}
      <PageHeader
        title={title}
        lead={subject.kind === "org" ? t("forOrg", { org: subject.membership.org_name }) : undefined}
      >
        {tag ? <p className="mt-3">{tag}</p> : null}
      </PageHeader>
      {children}
    </SignedInShell>
  );
  const empty = (sentence: string, action: string, href: string, primary = false) =>
    shell(
      t("pageTitle"),
      <EmptyState sentence={sentence} action={action} href={href} primary={primary} className="mt-8" />,
      undefined,
      false,
    );

  if (subject.kind === "notMember") return empty(t("refused.notMember"), t("action.billing"), "/billing");
  if (subject.kind === "noOrg") return empty(t("refused.noOrg"), t("action.home"), home);
  if (subject.kind === "notPayer") {
    return empty(t("refused.notPayer", { org: subject.membership.org_name }), t("action.home"), home);
  }

  const code = one(search.plan);
  const catalogue = isPlanCode(code) ? await getPlans(sideOf(subject)) : null;
  const plan = catalogue?.plans.find((p) => p.code === code);
  if (!catalogue || !plan) return empty(t("refused.unknownPlan"), t("action.allPlans"), back);

  const checkoutId = one(search.checkout);
  const resuming = isOrgId(checkoutId); // the same UUID pattern
  if (!resuming) {
    // Already on it: nothing to buy (a checkout in the address still shows its outcome, which activated it).
    const current = await getCurrentPlan(subject);
    if (current.kind === "refused") {
      const org = subject.kind === "org" ? subject.membership.org_name : "";
      return current.refusal === "mfaSetup"
        ? empty(t("refused.mfaSetup", { org }), t("action.turnOnMfa"), "/settings/security", true)
        : empty(t("refused.mfaRequired", { org }), t("action.enterCode"), "/auth/mfa");
    }
    if (current.code === plan.code) return empty(t("refused.alreadyOn", { plan: plan.name }), tc("backToBilling"), back);
  }
  // A free plan is never bought; the others that are not sold here (custom, approval, eligibility) say so.
  if (!plan.purchasable && plan.is_default) {
    return empty(t("refused.freePlan", { plan: plan.name }), t("action.allPlans"), back);
  }
  if (!plan.purchasable) return empty(t("refused.notSold", { plan: plan.name }), t("action.allPlans"), back);

  const [price, lines] = await Promise.all([priceText(plan), lineTexts(plan)]);
  // "Simulated" is a fact, said in words as a neutral Badge (p16-design-system.md, review against the brief).
  const simulatedTag = catalogue.simulated_checkout ? (
    <Badge data-simulated="" tone="neutral" icon={<InfoIcon />}>
      {tc("simulatedTag")}
    </Badge>
  ) : null;
  return shell(
    tc("pageTitle", { plan: plan.name }),
    <ClientStrings strings={await clientStrings(["checkout"])}>
      <Checkout
        plan={{ code: plan.code, name: plan.name }}
        price={price}
        lines={lines}
        sample={catalogue.sample_prices ? <SamplePrices label={t("samplePrices")} /> : undefined}
        simulated={catalogue.simulated_checkout}
        orgId={orgId}
        billingHref={back}
        nextHref={safeNext(one(search.next))}
        initialCheckoutId={resuming ? checkoutId : undefined}
        locale={await getLocale()}
      />
    </ClientStrings>,
    simulatedTag,
  );
}
