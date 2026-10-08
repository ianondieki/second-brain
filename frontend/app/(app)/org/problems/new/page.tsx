import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getBriefs } from "../../brief-data";
import { briefUpgrade, newBriefHref, planFull, postsBriefs, problemsHref, todayInNairobi } from "../../briefs";
import { orgContext } from "../../data";
import { OrgRefusal } from "../../OrgRefusal";
import { PlanNotice } from "../PlanNotice";
import { getCounties, getNicheTree, getVerification, readOrgPlans } from "../../scout-data";
import { BriefForm } from "./BriefForm";
import { BriefPreviewView } from "./BriefPreviewView";

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
  const tf = await getTranslations("briefForm");
  const back = org ? problemsHref(memberships, org.org_id) : "/org/problems";

  const frame = (body: ReactNode) => (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav current="problems" query={query} />} wide>
      <div className="max-w-5xl">
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
    readOrgPlans(),
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
  const full = planFull(plan);
  const notice = (
    <PlanNotice
      plan={plan}
      next={full && plans ? briefUpgrade(plans, plan.plan) : null}
      plansUnknown={full && plans === null}
      orgId={org.org_id}
      here={here}
    />
  );
  // With every open Brief in use the API would refuse the form (402), so the page says it once, with the way to more
  // room, instead of a form, a second notice and the same refusal after typing.
  if (full) return frame(notice);
  return frame(
    <>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{t("newLead")}</p>
      <div className="max-w-3xl">{notice}</div>
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
            planNames={Object.fromEntries((plans ?? []).map((p) => [p.code, p.name]))}
            doneHref={problemsHref(memberships, org.org_id, { posted: true })}
            hereHref={here}
            cancelHref={back}
            locale={await getLocale()}
            preview={
              <BriefPreviewView
                words={{
                  heading: tf("preview.title"),
                  title: tf("preview.untitled"),
                  niche: null,
                  place: tf("countyAny"),
                  postedBy: tf("preview.postedBy", { org: org.org_name }),
                  statement: tf("preview.statement"),
                  budget: tf("preview.noBudget"),
                  deadline: tf("preview.noDeadline"),
                  note: tf("preview.note"),
                }}
              />
            }
          />
        </ClientStrings>
      </div>
    </>,
  );
}
