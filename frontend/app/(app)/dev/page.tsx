import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { myEngagements } from "@/components/tracker/data";
import { EngagementRow } from "@/components/tracker/EngagementRow";
import { Badge } from "@/components/ui/Badge";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { homeFor, needsMfaSetup } from "@/lib/auth/routing";

import { recommendations } from "./discover/data";
import { RecommendedForYou } from "./discover/RecommendedForYou";
import { recommendationsState } from "./discover/recommendations";
import { homeGroups } from "./home";
import { myIdeas } from "./ideas/data";
import { IdeaRow } from "./ideas/IdeaRow";
import { NEW_PATH } from "./ideas/ideas";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("devPageTitle") };
}

/** How many of the engagements not waiting on the developer, and of their ideas, Home lists before "All …". */
const OTHERS_SHOWN = 5;
const IDEAS_SHOWN = 3;
const ENGAGEMENTS_PATH = "/dev/engagements";

/**
 * Developer Home (docs/spec/07 item 1, prototype part): the engagements waiting on the developer, each linking to its
 * tracker, then the others; then their latest ideas. "New proposal" is the screen's one primary action (a button, not
 * a nav item); with no engagements yet, an empty state points to My ideas. The two-step sign-in status stays, since
 * signing and payments need it. "Recommended for you" (P12) follows what needs the developer; the reminder summary
 * comes with P6's in-app route. Composed from the design system: PageHeader, Sections of RowLists, Badges.
 */
export default async function DeveloperHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("devHome");
  const th = await getTranslations("home");
  const [engagements, ideas, recommended] = await Promise.all([myEngagements(), myIdeas(), recommendations()]);
  const { waiting, others } = homeGroups(engagements);
  const mfa = me.mfa.enrolled ? "on" : needsMfaSetup(me.mfa) ? "required" : "off";
  const MfaIcon = mfa === "on" ? CheckIcon : mfa === "required" ? AlertIcon : InfoIcon;

  const rowHref = (id: string) => `${ENGAGEMENTS_PATH}/${encodeURIComponent(id)}`;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="home" />} wide>
      <div className="max-w-3xl">
        <PageHeader
          title={th("title", { name: me.user.display_name })}
          lead={t("lead")}
          action={
            <ButtonLink href={NEW_PATH} variant="primary">
              <PlusIcon />
              {t("newProposal")}
            </ButtonLink>
          }
        />
      </div>

      <div className="mt-10 flex max-w-3xl flex-col gap-12">
        {engagements.length === 0 ? (
          <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/dev/ideas" />
        ) : null}

        {waiting.length > 0 ? (
          <Section title={t("needsYou")} headingId="home-needs-you" data-home="needs-you">
            <RowList>
              {waiting.map((item) => (
                <EngagementRow key={item.id} item={item} mine="developer" href={rowHref(item.id)} />
              ))}
            </RowList>
          </Section>
        ) : null}

        <RecommendedForYou state={recommendationsState(recommended)} />

        {others.length > 0 ? (
          <Section
            title={t("others")}
            headingId="home-others"
            data-home="others"
            link={{ href: ENGAGEMENTS_PATH, label: t("allEngagements") }}
          >
            <RowList>
              {others.slice(0, OTHERS_SHOWN).map((item) => (
                <EngagementRow key={item.id} item={item} mine="developer" href={rowHref(item.id)} />
              ))}
            </RowList>
          </Section>
        ) : null}

        {ideas.length > 0 ? (
          <Section
            title={t("ideasTitle")}
            headingId="home-ideas"
            data-home="ideas"
            link={{ href: "/dev/ideas", label: t("allIdeas") }}
          >
            <RowList>
              {ideas.slice(0, IDEAS_SHOWN).map((item) => (
                <IdeaRow key={item.id} item={item} headingLevel={3} />
              ))}
            </RowList>
          </Section>
        ) : null}

        <Section title={t("security")} headingId="home-security" data-home="security">
          <div className="flex flex-col items-start gap-1">
            <Badge tone={mfa === "on" ? "ok" : mfa === "required" ? "error" : "neutral"} icon={<MfaIcon />}>
              {mfa === "on" ? th("mfaOn") : mfa === "required" ? th("mfaRequired") : th("mfaOff")}
            </Badge>
            <Link href="/settings/security" className={standaloneLinkClass}>
              {me.mfa.enrolled ? th("manage") : th("setUp")}
            </Link>
          </div>
        </Section>
      </div>
    </SignedInShell>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="size-5 shrink-0">
      <path d="M10 4.5v11M4.5 10h11" />
    </svg>
  );
}
