import Link from "next/link";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";
import { clientStrings } from "@/lib/i18n/client-strings";

import { orgContext } from "../../data";
import { EmptyState } from "@/components/ui/EmptyState";
import { first } from "../../membership";
import { OrgRefusal } from "../../OrgRefusal";
import { configuresScouts, FREQUENCIES, matchesHref, planFor, scoutHref, type Frequency, type ScoutPlan } from "../../scout";
import {
  getCounties,
  getMembers,
  getNicheTree,
  getOrgPlans,
  getScout,
  getScouts,
  getVerification,
} from "../../scout-data";
import { ScoutForm } from "./ScoutForm";

/**
 * Organisation › Inbox › Configure scout (REQ-SCOUT-01; docs/spec/07 item 1 "Configure scout: form + Preview + pause"),
 * for the organisation's owners and admins: what the plan includes, a note while the organisation is not yet verified
 * (AC-SCOUT-8: it previews, digests start once verified), then the form. `scoutId` absent: a new scout.
 */
export async function ScoutScreen({
  scoutId,
  org: requested,
  restore,
}: {
  scoutId?: string;
  org: string | string[] | undefined;
  /** ?restore=1: back from the checkout, so the kept draft comes back. */
  restore?: string | string[] | undefined;
}) {
  const { me, memberships, org, missing, query } = await orgContext(requested);
  const t = await getTranslations("scoutPage");
  const ti = await getTranslations("inbox");
  const nav = <OrgNav current="inbox" query={query} />;
  const back = org ? matchesHref(memberships, org.org_id) : "/org/inbox?tab=matches";

  const frame = (title: string, body: ReactNode) => (
    <SignedInShell homeHref={`/org${query}`} nav={nav} wide>
      <div className="max-w-3xl">
        <Link href={back} className={standaloneLinkClass}>
          {t("back")}
        </Link>
        <h1 className="mt-4 text-xl text-ink lg:text-2xl">{title}</h1>
        {body}
      </div>
    </SignedInShell>
  );
  const title = scoutId ? t("titleEdit") : t("titleNew");

  if (!org) {
    return frame(
      title,
      <div className="mt-6">
        {missing === "notMember" ? (
          <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
        ) : (
          <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
        )}
      </div>,
    );
  }
  if (!configuresScouts(org)) {
    return frame(
      title,
      <div className="mt-6">
        <EmptyState sentence={t("notAdmin", { org: org.org_name })} action={t("back")} href={back} />
      </div>,
    );
  }

  const [list, scout, niches, counties, members, verification, plans] = await Promise.all([
    getScouts(org.org_id),
    scoutId ? getScout(org.org_id, scoutId) : Promise.resolve(undefined),
    getNicheTree(),
    getCounties(),
    getMembers(org.org_id),
    getVerification(org.org_id),
    getOrgPlans(),
  ]);
  if (list.kind === "refused" || scout === null || scout?.kind === "refused") {
    const refused = list.kind === "refused" ? list.refusal : scout?.kind === "refused" ? scout.refusal : null;
    return frame(
      title,
      <div className="mt-6">
        {refused ? (
          <OrgRefusal refusal={refused} orgName={org.org_name} back={{ href: back, action: t("back") }} />
        ) : (
          <EmptyState sentence={t("notFound")} action={t("back")} href={back} />
        )}
      </div>,
    );
  }

  const plan: ScoutPlan = list.value.plan;
  // The plan to buy for each schedule this plan lacks, so the form can say so as soon as one is chosen.
  const upgradeFor: Partial<Record<Frequency, string | null>> = Object.fromEntries(
    FREQUENCIES.filter((f) => !plan.frequencies.includes(f)).map((f) => [f, planFor(plans, plan.plan, f)]),
  );
  // null: the members could not be read (never taken as "no reviewers", which would empty the saved recipients).
  const reviewers =
    members === null
      ? null
      : members.filter((m) => m.roles.includes("reviewer")).map((m) => ({ id: m.user_id, label: m.display_name }));
  const pending = verification !== null && verification !== "e1" && verification !== "e2";
  return frame(
    title,
    <>
      <p className="mt-2 max-w-[62ch] text-ink-soft">{t("lead")}</p>
      <p className="mt-4 text-sm text-ink" data-plan-cap={plan.scout_agents ?? "unlimited"}>
        {plan.scout_agents === null ? t("capUnlimited") : t("cap", { count: plan.scout_agents })}
      </p>
      {pending ? (
        <p className="mt-4 max-w-[62ch] border-l-2 border-jacaranda pl-3 text-ink">
          {t("pending", { org: org.org_name })}
        </p>
      ) : null}
      <div className="mt-8">
        <ClientStrings strings={await clientStrings(["scoutForm", "ideaFields"])}>
          <ScoutForm
            userId={me.user.id}
            restore={first(restore) === "1"}
            orgId={org.org_id}
            orgName={org.org_name}
            scout={scout?.value}
            plan={plan}
            niches={niches.map((n) => ({
              id: n.id,
              name: n.name,
              children: n.children.map((c) => ({ id: c.id, name: c.name })),
            }))}
            counties={counties.map((c) => ({ id: c.code, label: c.name }))}
            reviewers={reviewers}
            doneHref={back}
            hereHref={scoutHref(memberships, org.org_id, scoutId, { restore: true })}
            upgradeFor={upgradeFor}
          />
        </ClientStrings>
      </div>
    </>,
  );
}
