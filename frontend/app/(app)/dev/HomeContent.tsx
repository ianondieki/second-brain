import { cookies } from "next/headers";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { Chip } from "@/components/tracker/Chip";
import { dueAt, stageChip, type Summary } from "@/components/tracker/model";
import { DueLine } from "@/components/tracker/When";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { AlertIcon, InfoIcon } from "@/components/ui/icons";
import { Callout } from "@/components/ui/Callout";
import { PageHeader } from "@/components/ui/PageHeader";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { StatTile } from "@/components/ui/StatTile";
import { TimeLeft } from "@/components/ui/TimeLeft";
import { ClientStrings } from "@/components/ClientStrings";
import { FirstLoginTour } from "@/components/tour/FirstLoginTour";
import { tourDoneFromCookies } from "@/components/tour/tour-store";
import { tourScenes } from "@/components/tour/TourScenes";
import { clientStrings } from "@/lib/i18n/client-strings";
import { needsMfaSetup, type Me } from "@/lib/auth/routing";
import { formatShortDate } from "@/lib/format";

import { RecommendedForYou } from "./discover/RecommendedForYou";
import type { RecommendationsState } from "./discover/recommendations";
import { homeGroups, homeStats } from "./home";
import { IdeaCard } from "./ideas/IdeaCard";
import { NEW_PATH, type MyProposalItem } from "./ideas/ideas";
import { NeedsYouHero } from "./NeedsYouHero";
import { PeersSection } from "./peers/PeersSection";
import type { QuizCardState } from "./quiz/quiz";
import { QuizCard } from "./quiz/QuizCard";
import type { PeersPage } from "./teams/teams";
import type { Week } from "./week/week";
import { WeekStrip } from "./week/WeekStrip";

/** How many of the engagements not waiting on the developer, and of their ideas, Home shows before "All …". */
const OTHERS_SHOWN = 4;
const IDEAS_SHOWN = 4;
const ENGAGEMENTS_PATH = "/dev/engagements";

export interface HomeContentProps {
  me: Me;
  engagements: readonly Summary[];
  ideas: readonly MyProposalItem[];
  recommended: RecommendationsState;
  /** Today's five (REQ-DEV-01): left out when null or not given (the read failed, or a fixture without it). */
  quiz?: QuizCardState;
  /** This week (REQ-DEV-02): left out when null or not given (the read failed, or a fixture without it). */
  week?: Week | null;
  /** Peers (REQ-DEV-03): left out when null or not given (the read failed, or a fixture without it). */
  peers?: PeersPage | null;
  /** The app clock's instant for this page (lib/api/server.ts appNow): the countdowns count from it. */
  now?: string;
}

/**
 * Developer Home (docs/spec/07 item 1; D-52, P20): four stat tiles, then what needs the developer as the page's one
 * raised card each (the deadline as a figure, one way in), "Recommended for you" three across, then the rest as two
 * lists of rows side by side on a wide column (the other engagements, the ideas). "New proposal" is the screen's one
 * primary action. The tiles count what the page already reads: no series exists for them yet, so no sparkline.
 */
export async function HomeContent({
  me,
  engagements,
  ideas,
  recommended,
  quiz = null,
  week = null,
  peers = null,
  now = new Date().toISOString(),
}: HomeContentProps) {
  const [t, th, tr, locale] = await Promise.all([
    getTranslations("devHome"),
    getTranslations("home"),
    getTranslations("tracker"),
    getLocale(),
  ]);
  const { waiting, others } = homeGroups(engagements);
  const stats = homeStats(engagements, ideas);
  const mfa = me.mfa.enrolled ? "on" : needsMfaSetup(me.mfa) ? "required" : "off";
  const rowHref = (id: string) => `${ENGAGEMENTS_PATH}/${encodeURIComponent(id)}`;
  const due = stats.nextDue;
  const dueWords = due
    ? due.overdue
      ? t("stats.deadlineOverdue")
      : due.business_days_left === 0
        ? t("stats.deadlineToday")
        : t("stats.deadlineMeta", { count: due.business_days_left })
    : undefined;
  const until = due && !due.overdue ? dueAt(due) : null;

  const tourDone = tourDoneFromCookies(await cookies(), "developer");
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <ClientStrings strings={await clientStrings(["tour"])}>
        <FirstLoginTour side="developer" initialDone={tourDone} scenes={tourDone ? undefined : tourScenes("developer")} />
      </ClientStrings>
      <div className="max-w-4xl">
        <PageHeader
          title={th("title", { name: me.user.display_name })}
          lead={t("lead")}
          action={
            <ButtonLink href={NEW_PATH} variant="primary">
              {t("newProposal")}
            </ButtonLink>
          }
        />
      </div>

      <div className="mt-8 flex max-w-4xl flex-col gap-12 lg:gap-14">
        <section aria-label={t("stats.label")} data-home="stats">
          <ul className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <li>
              <StatTile data-stat="ideas" label={t("stats.ideas")} value={stats.ideas} meta={t("stats.ideasMeta", { published: stats.published, drafts: stats.drafts })} href="/dev/ideas" />
            </li>
            <li>
              <StatTile data-stat="engagements" label={t("stats.engagements")} value={stats.engagements} meta={t("stats.engagementsMeta", { count: stats.active })} href={ENGAGEMENTS_PATH} />
            </li>
            <li>
              <StatTile data-stat="needs-you" label={t("stats.needsYou")} value={waiting.length} meta={waiting.length > 0 ? t("stats.needsYouMeta") : undefined} />
            </li>
            <li>
              <StatTile
                data-stat="deadline"
                label={t("stats.deadline")}
                value={stats.nextDue ? formatShortDate(locale, stats.nextDue.due_on) : t("stats.deadlineNone")}
                // The time left in days, hours and minutes (P23-3) when the API gives the instant, the business days
                // then in the tile's title; otherwise the business days as the meta line.
                meta={
                  until ? <TimeLeft until={until} now={now} labelWhenPast={t("stats.deadlineOverdue")} mine={stats.nextDueMine} /> : dueWords
                }
                title={until ? dueWords : undefined}
                href={stats.nextDueId ? rowHref(stats.nextDueId) : undefined}
              />
            </li>
          </ul>
        </section>

        {/* Two-step sign-in: a notice only while it is off (the status needs no section of its own when it is on). */}
        {mfa !== "on" ? (
          <Callout tone={mfa === "required" ? "error" : "info"} icon={mfa === "required" ? <AlertIcon className="mt-0.5 size-5 shrink-0 text-error" /> : <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />} data-home="security">
            <p>{mfa === "required" ? th("mfaRequired") : th("mfaOff")}</p>
            <Link href="/settings/security" className={standaloneLinkClass}>
              {th("setUp")}
            </Link>
          </Callout>
        ) : null}

        {engagements.length === 0 ? (
          <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/dev/ideas" />
        ) : null}

        {waiting.length > 0 ? (
          <Section title={t("needsYou")} headingId="home-needs-you" data-home="needs-you">
            <ul className="flex flex-col gap-4">
              {waiting.map((item) => (
                <li key={item.id}>
                  <NeedsYouHero item={item} href={rowHref(item.id)} action={t("openTracker")} now={now} />
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        <QuizCard state={quiz} />

        <WeekStrip week={week} />

        <PeersSection peers={peers} />

        <RecommendedForYou state={recommended} />

        {others.length > 0 || ideas.length > 0 ? (
          // Two lists of rows: side by side from 1024 px when both are there, one column (or the full width) otherwise.
          <div className="grid gap-12 lg:auto-cols-fr lg:grid-flow-col lg:gap-10">
            {others.length > 0 ? (
              <Section
                title={t("others")}
                headingId="home-others"
                data-home="others"
                link={{ href: ENGAGEMENTS_PATH, label: t("allEngagements") }}
              >
                <RowList>
                  {others.slice(0, OTHERS_SHOWN).map((item) => (
                    <Row
                      key={item.id}
                      data-engagement={item.id}
                      href={rowHref(item.id)}
                      title={item.proposal_title}
                      meta={tr("withOrg", { org: item.org_name })}
                      badges={[<Chip key="stage" kind={stageChip(item)}>{item.stage_label}</Chip>]}
                    >
                      <DueLine item={item} mine="developer" />
                    </Row>
                  ))}
                </RowList>
              </Section>
            ) : null}

            {ideas.length > 0 ? (
              <Section title={t("ideasTitle")} headingId="home-ideas" data-home="ideas" link={{ href: "/dev/ideas", label: t("allIdeas") }}>
                <RowList>
                  {ideas.slice(0, IDEAS_SHOWN).map((item) => (
                    <IdeaCard key={item.id} item={item} headingLevel={3} />
                  ))}
                </RowList>
              </Section>
            ) : null}
          </div>
        ) : null}
      </div>
    </SignedInShell>
  );
}
