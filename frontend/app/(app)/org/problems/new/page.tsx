import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { upgradeHref } from "@/lib/billing/upgrade";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getBriefs } from "../../brief-data";
import { briefUpgrade, newBriefHref, planFull, postsBriefs, problemsHref, todayInNairobi } from "../../briefs";
import { orgContext } from "../../data";
import { OrgRefusal } from "../../OrgRefusal";
import { getCounties, getNicheTree, getOrgPlans, getVerification } from "../../scout-data";
import { BriefForm } from "./BriefForm";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("briefs");
  return { title: t("newTitle") };
}

/**
 * Organisation › Problems › Post a brief (REQ-DIR-05; docs/spec/06 6.2 last bullet, docs/spec/07 item 1). For the
 * organisation's owners, admins, signatories and reviewers of a legally verified (E2) organisation: anyone else reads
 * one sentence and one way back. What the plan allows comes first, then the form.
 */
export default async function NewBriefPage({ searchParams }: PageProps<"/org/problems/new">) {
  const { memberships, org, missing, query } = await orgContext((await searchParams).org);
  const t = await getTranslations("briefs");
  const ti = await getTranslations("inbox");
  const back = org ? problemsHref(memberships, org.org_id) : "/org/problems";

  const frame = (body: ReactNode) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="problems" query={query} />} wide>
      <div className="max-w-3xl">
        <PageHeader back={{ href: back, label: t("back") }} title={t("newTitle")} />
        {body}
      </div>
    </SignedInShell>
  );

  if (!org) {
    return frame(
      <div className="mt-6">
        {missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        )}
      </div>,
    );
  }
  if (!postsBriefs(org)) {
    return frame(
      <div className="mt-6">
        <EmptyState sentence={t("notEditor", { org: org.org_name })} action={t("back")} href={back} />
      </div>,
    );
  }

  const [list, verification, niches, counties, plans] = await Promise.all([
    getBriefs(org.org_id),
    getVerification(org.org_id),
    getNicheTree(),
    getCounties(),
    getOrgPlans(),
  ]);
  if (list.kind !== "ok") {
    return frame(
      <div className="mt-6">
        {list.kind === "refused" ? (
          <OrgRefusal refusal={list.refusal} orgName={org.org_name} back={{ href: back, action: t("back") }} />
        ) : (
          <EmptyState sentence={t("notFound")} action={t("back")} href={back} />
        )}
      </div>,
    );
  }
  // Only a legally verified organisation posts (the API answers 403 verification_required otherwise); null (not read)
  // shows the form, and the API's answer is worded there.
  if (verification !== null && verification !== "e2") {
    return frame(
      <div className="mt-6">
        <EmptyState sentence={t("notVerified", { org: org.org_name })} action={t("back")} href={back} />
      </div>,
    );
  }

  const { plan, budget_bands: bands } = list.value;
  const here = newBriefHref(memberships, org.org_id);
  const next = planFull(plan) ? briefUpgrade(plans, plan.plan) : null;
  return frame(
    <>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{t("newLead")}</p>
      <p className="mt-4 text-sm text-ink" data-plan-cap={plan.problem_briefs ?? "unlimited"}>
        {plan.problem_briefs === null ? t("capUnlimited") : t("cap", { used: plan.used, limit: plan.problem_briefs })}
      </p>
      {planFull(plan) ? (
        <Callout className="mt-4 max-w-[62ch]" data-plan-full="">
          <p>{next ? t("capFull") : t("capFullTop")}</p>
          {next ? (
            <Link href={upgradeHref(next.code, { org: org.org_id, next: here })} className={standaloneLinkClass}>
              {t("upgrade")}
            </Link>
          ) : null}
        </Callout>
      ) : null}
      <div className="mt-8">
        <ClientStrings strings={await clientStrings(["briefForm"])}>
          <BriefForm
            orgId={org.org_id}
            orgName={org.org_name}
            niches={niches.map((n) => ({ id: n.id, name: n.name, children: n.children.map((c) => ({ id: c.id, name: c.name })) }))}
            counties={counties.map((c) => ({ id: c.code, label: c.name }))}
            bands={bands}
            today={todayInNairobi()}
            planLimit={plan.problem_briefs}
            planNames={Object.fromEntries(plans.map((p) => [p.code, p.name]))}
            doneHref={problemsHref(memberships, org.org_id, { posted: true })}
            hereHref={here}
            cancelHref={back}
          />
        </ClientStrings>
      </div>
    </>,
  );
}
