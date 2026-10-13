import type { Metadata } from "next";
import { unstable_rethrow } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { CheckIcon } from "@/components/ui/status-icons";
import { clientStrings, pickedStrings } from "@/lib/i18n/client-strings";
import { billingHref, upgradeHref } from "@/lib/billing/upgrade";
import { publicDemoOn } from "@/lib/public-demo";

import { orgContext } from "../data";
import { OrgRefusal } from "../OrgRefusal";
import { OrgPicker } from "../OrgPicker";
import { getVerification, readOrgPlans } from "../scout-data";
import { TEAM_PATH, type Paywall } from "./team";
import { getOrgNiches, getTeam } from "./team-data";
import { TeamView } from "./TeamView";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("orgTeam");
  return { title: t("pageTitle") };
}

/** The organisation's verification level, or null when it cannot be read in time (the hero then leaves it out). */
async function verificationOf(orgId: string) {
  try {
    return await getVerification(orgId);
  } catch (error) {
    unstable_rethrow(error); // the session ended: the redirect to sign in still happens
    return null;
  }
}

/**
 * The seats paywall's links (402 plan_limit): each organisation plan's name and checkout, coming back to this page, and
 * Plan & billing for anything else (or when the plans cannot be read).
 */
async function paywallFor(orgId: string): Promise<Paywall> {
  const back = `${TEAM_PATH}?org=${orgId}`;
  let plans: { code: string; name: string }[] = [];
  try {
    plans = (await readOrgPlans()) ?? [];
  } catch (error) {
    unstable_rethrow(error);
  }
  return {
    plans: Object.fromEntries(
      plans.map((plan) => [plan.code, { name: plan.name, href: upgradeHref(plan.code, { org: orgId, next: back }) }]),
    ),
    billing: billingHref(orgId),
  };
}

/**
 * Organisation › Team (REQ-TEN-02; docs/spec/07 item 1 "Team: members, roles, default assignee per niche, escalation
 * contact, verification status"; docs/platform/tasks/P28.md track C). Reached from the account menu and the command
 * palette on organisation screens: the portal's five sections are taken (components/OrgNav.tsx). The hero names the
 * organisation's verification level (the API models no person's own); the sections below are TeamView's. Members of
 * several organisations pick one (?org=); an organisation the person is not a member of is refused, never swapped.
 */
export default async function OrganisationTeamPage({ searchParams }: PageProps<"/org/team">) {
  const { me, memberships, org, missing, query } = await orgContext((await searchParams).org);
  const [t, tp] = await Promise.all([getTranslations("orgTeam"), getTranslations("portal")]);

  let body;
  let verification = null;
  if (!org) {
    body =
      missing === "notMember" ? (
        <EmptyState sentence={t("notMember")} action={t("openOwn")} href={TEAM_PATH} />
      ) : (
        <EmptyState
          sentence={(await getTranslations("inbox"))("noOrg")}
          action={(await getTranslations("inbox"))("emptyAction")}
          href="/org"
        />
      );
  } else {
    const [read, niches, level, paywall] = await Promise.all([
      getTeam(org.org_id),
      getOrgNiches(org.org_id),
      verificationOf(org.org_id),
      paywallFor(org.org_id),
    ]);
    verification = level;
    if (read.kind === "refused") {
      body =
        read.refusal === "generic" ? (
          <EmptyState sentence={t("readFailed")} action={t("retry")} href={`${TEAM_PATH}${query}`} />
        ) : (
          <OrgRefusal refusal={read.refusal} orgName={org.org_name} back={{ href: "/org", action: t("openOwn") }} />
        );
    } else {
      // The forms' words (teamAdmin) and the fresh-code step's (the tracker's StepUp, picked): the client islands get
      // plain strings formatted here, no message runtime (lib/i18n/client-strings.ts).
      const strings = {
        ...(await clientStrings(["teamAdmin"])),
        ...(await pickedStrings("trackerActions", ["stepUp", "cancel", "refusal"])),
      };
      body = (
        <ClientStrings strings={strings}>
          <TeamView
            team={read.team}
            orgId={org.org_id}
            orgName={org.org_name}
            me={{ userId: me.user.id, roles: org.roles, enrolled: me.mfa.enrolled }}
            niches={niches}
            paywall={paywall}
            demo={publicDemoOn()}
          />
        </ClientStrings>
      );
    }
  }

  return (
    <SignedInShell homeHref={`/org${query}`} nav={<OrgNav query={query} />} wide>
      <div className="max-w-5xl">
        <PageHero
          eyebrow={tp("eyebrow.team")}
          title={t("title")}
          lead={org ? t("lead", { org: org.org_name }) : undefined}
        >
          {verification ? (
            <p className="mt-4" data-verification={verification}>
              <Badge
                tone={verification === "e2" ? "ok" : verification === "e1" ? "accent" : "neutral"}
                icon={verification === "e2" || verification === "e1" ? <CheckIcon /> : undefined}
              >
                {t(`verification.${verification}`)}
              </Badge>
            </p>
          ) : null}
        </PageHero>
        {org && memberships.length > 1 ? (
          <div className="mb-8">
            <OrgPicker memberships={memberships} current={org.org_id} action={TEAM_PATH} />
          </div>
        ) : null}
        {body}
      </div>
    </SignedInShell>
  );
}
