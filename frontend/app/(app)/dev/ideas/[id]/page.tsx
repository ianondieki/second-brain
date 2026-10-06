import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DevNav } from "@/components/DevNav";
import { ClientStrings } from "@/components/ClientStrings";
import { SignedInShell } from "@/components/SignedInShell";
import { ProblemLabelText } from "@/components/problem/ProblemLabelText";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { Callout, type CalloutTone } from "@/components/ui/Callout";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { LockIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { Panel } from "@/components/ui/Panel";
import { Section } from "@/components/ui/Section";
import { requireMe } from "@/lib/api/server";
import { clientStrings } from "@/lib/i18n/client-strings";
import { homeFor } from "@/lib/auth/routing";

import { countyName, myIdea } from "../data";
import {
  BASE_PATH,
  editHref,
  MATURITY_KEY,
  type MyProposal,
  type Version,
} from "../ideas";
import { fileSizeParts } from "../files";
import { ideaStatus, type IdeaStatus } from "../status";
import { IdeaStatusBadge } from "../IdeaStatusBadge";
import { DeleteIdea } from "./DeleteIdea";
import { ideaTags, ideaViews } from "./pitch/data";
import { pitchesLeft, pitchHref } from "./pitch/picker";
import { Pitches } from "./Pitches";
import { Certificate } from "./Certificate";
import { ContributorsLine } from "./ContributorsLine";
import { ideaContributors } from "../../teams/data";
import { WhoHasSeen } from "./WhoHasSeen";

export async function generateMetadata({ params }: PageProps<"/dev/ideas/[id]">): Promise<Metadata> {
  const t = await getTranslations("ideas");
  const idea = await myIdea((await params).id).catch(() => null);
  const version = idea ? (idea.current ?? idea.draft) : null;
  return { title: version?.teaser.title || t("pageTitle") };
}

/** The version the page shows: the published one when there is one, else the draft. */
function shownVersion(idea: MyProposal): Version | null {
  return idea.current ?? idea.draft;
}

/**
 * One of your ideas (REQ-PROP-01, REQ-PROV-02): status and any moderation hold, the public teaser, the confidential
 * full details (yours only), and the certificate with its /verify link and PDF. Once registered: its pitches with the
 * plan's cap and "Who has seen this" (REQ-PROP-03, REQ-PROV-03). The one primary action is "Pitch to companies" for a
 * published idea with pitches left, else "Edit idea" (or "Continue editing"); a hidden idea has none.
 */
export default async function IdeaPage({ params, searchParams }: PageProps<"/dev/ideas/[id]">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("ideas");
  const idea = await myIdea((await params).id);
  const justPublished = (await searchParams).published === "1";

  if (!idea) {
    return (
      <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
        <PageHeader title={t("title")} />
        <EmptyState className="mt-8" sentence={t("notFound")} action={t("back")} href={BASE_PATH} />
      </SignedInShell>
    );
  }

  const status = ideaStatus(idea.status, idea.moderation.state);
  const version = shownVersion(idea);
  const hasChanges = idea.current !== null && idea.draft !== null;
  const notice = noticeFor(status, hasChanges);
  // Once the idea is known to be yours: its pitches and views (a registered idea only) and the county's name are read
  // together, not one after the other.
  const countyCode = version?.teaser.county_code;
  // Contributors' handles (REQ-DEV-03; D-62 (a)); an answer from before P22-C has none.
  const contributors = idea.contributors ?? [];
  const [tags, views, county, credited] = await Promise.all([
    idea.current ? ideaTags(idea.id) : null,
    idea.current ? ideaViews(idea.id) : null,
    countyCode ? countyName(countyCode) : null,
    idea.current ? ideaContributors(idea.id) : null,
  ]);
  const canPitch = status === "published" && tags !== null && pitchesLeft(tags.cap) !== 0;
  // An idea that answers an organisation's Problem Brief pitches with that organisation chosen first (REQ-DIR-05).
  const briefOrg = (idea.current ?? version)?.problems.find((problem) => problem.source === "org_brief" && problem.org)?.org?.id;
  const p = await getTranslations("ideaPitches");

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />} wide>
      <div className="max-w-4xl">
        <PageHeader back={{ href: BASE_PATH, label: t("back") }} title={version?.teaser.title?.trim() || t("untitled")}>
          <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
            <IdeaStatusBadge status={status} />
            {idea.current ? (
              <span className="text-sm text-ink-soft">{t("version", { number: idea.current.version_no })}</span>
            ) : null}
          </p>
          {/* D-62 (a): the contributors the owner credited, by handle, each with Remove (when the credit could be read;
              kept on a registered idea with none, so the status line after the last Remove stays). */}
          {credited ? (
            <ClientStrings strings={await clientStrings(["ideaContributors"])}>
              <ContributorsLine ideaId={idea.id} initial={credited} />
            </ClientStrings>
          ) : contributors.length > 0 ? (
            <p className="mt-3 text-ink" data-contributors="">
              {t("contributorsLine", { handles: new Intl.ListFormat(await getLocale(), { type: "conjunction" }).format(contributors) })}
            </p>
          ) : null}
        </PageHeader>

        {justPublished && idea.current?.cert_id ? (
          <Alert tone="ok" className="mt-6 max-w-2xl">
            {t("published", { certId: idea.current.cert_id })}
          </Alert>
        ) : null}
        {/* The idea's standing is part of the page from the start: a static Callout, not an announced Alert. */}
        {notice ? (
          <Callout tone={notice.tone} className="mt-6 max-w-2xl">
            <p>{t(notice.key)}</p>
          </Callout>
        ) : null}

        {status !== "hidden" ? (
          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            {canPitch ? (
              <ButtonLink href={pitchHref(idea.id, { selected: [], org: briefOrg })} variant="primary">
                {p("pitch")}
              </ButtonLink>
            ) : null}
            <ButtonLink href={editHref(idea.id)} variant={canPitch ? "secondary" : "primary"}>
              {idea.draft ? t("continueDraft") : t("edit")}
            </ButtonLink>
          </div>
        ) : null}

        {/* From 1024 px the certificate and, beside it, the pitches and the views share the first band; the teaser
            and the full details follow in one reading column. The reading order is unchanged. */}
        <div className="mt-10 grid grid-cols-1 gap-12 lg:mt-12 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start lg:gap-x-10">
          <Certificate idea={idea} ownerName={me.user.display_name} />
          {idea.current ? (
            <div className="flex min-w-0 flex-col gap-12">
              {status !== "hidden" || (tags?.items.length ?? 0) > 0 ? <Pitches ideaId={idea.id} status={status} tags={tags} /> : null}
              <WhoHasSeen views={views} />
            </div>
          ) : null}
          <div className="flex max-w-2xl min-w-0 flex-col gap-12 lg:col-span-2">
            {version ? <Teaser version={version} status={status} county={county} /> : null}
            {version ? <Confidential version={version} /> : null}

            {status !== "hidden" ? (
              <div>
                <ClientStrings strings={await clientStrings(["ideaDelete"])}>
                  <DeleteIdea id={idea.id} registered={idea.current !== null} />
                </ClientStrings>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </SignedInShell>
  );
}

type NoticeKey = "heldNotice" | "rejectedNotice" | "hiddenNotice" | "changesNotice" | "draftNotice";

function noticeFor(status: IdeaStatus, hasChanges: boolean): { key: NoticeKey; tone: CalloutTone } | null {
  if (status === "held") return { key: "heldNotice", tone: "info" };
  if (status === "rejected") return { key: "rejectedNotice", tone: "error" };
  if (status === "hidden") return { key: "hiddenNotice", tone: "info" };
  if (status === "draft") return { key: "draftNotice", tone: "info" };
  return hasChanges ? { key: "changesNotice", tone: "info" } : null;
}

/** Who sees the teaser now, in the tense of the idea's status. */
const TEASER_HINT = {
  draft: "teaserHint",
  published: "teaserHintPublished",
  held: "teaserHintHeld",
  rejected: "teaserHintHidden",
  hidden: "teaserHintHidden",
} as const satisfies Record<IdeaStatus, string>;

async function Teaser({
  version,
  status,
  county,
}: {
  version: Version;
  status: IdeaStatus;
  /** The county's name, read with the page's other reads (null when the teaser names none). */
  county: string | null;
}) {
  const f = await getTranslations("ideaFields");
  const { teaser } = version;
  const empty = <span className="text-ink-soft">{f("notGiven")}</span>;
  return (
    <Section title={f("teaserTitle")} headingId="teaser-heading" description={f(TEASER_HINT[status])}>
      <DescriptionList>
        <Description label={f("niche")}>{teaser.niche?.label ?? empty}</Description>
        <Description label={f("maturity")}>{teaser.maturity ? f(`maturityValue.${MATURITY_KEY[teaser.maturity]}`) : empty}</Description>
        <Description label={f("ask")}>{teaser.ask ? f(`askValue.${teaser.ask}`) : empty}</Description>
        <Description label={f("problems")}>
          {version.problems.length > 0 || version.new_problem ? (
            <ul className="flex flex-col gap-1">
              {version.problems.map((problem) => (
                <li key={problem.id} className="flex flex-col">
                  <span>{problem.title}</span>
                  {/* Its provenance, as Discover and the problem page word it. */}
                  <span className="text-sm text-ink-soft">
                    <ProblemLabelText problem={problem} />
                  </span>
                </li>
              ))}
              {version.new_problem ? (
                <li className="flex flex-col">
                  <span>{version.new_problem.title}</span>
                  <span className="text-sm text-ink-soft">{f("developerReported")}</span>
                </li>
              ) : null}
            </ul>
          ) : (
            empty
          )}
        </Description>
        <Description label={f("problemStatement")}>{prose(teaser.problem_statement) ?? empty}</Description>
        <Description label={f("summary")}>{prose(teaser.summary) ?? empty}</Description>
        {teaser.impact_claims ? <Description label={f("impactClaims")}>{prose(teaser.impact_claims)}</Description> : null}
        {county ? <Description label={f("county")}>{county}</Description> : null}
      </DescriptionList>
    </Section>
  );
}

async function Confidential({ version }: { version: Version }) {
  const f = await getTranslations("ideaFields");
  const t = await getTranslations("ideas");
  const { confidential } = version;
  const written = (["approach", "architecture", "pricing", "notes"] as const).filter((key) => confidential[key]);
  const nothing = written.length === 0 && confidential.links.length === 0 && confidential.attachments.length === 0;
  return (
    // The screen's one Panel: the full details are set apart as the part only the owner (and, after the NDA, verified
    // viewers) can read; its lock Badge says so in words (no coloured left rule).
    <Panel as="div">
      <Section
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {f("confidentialTitle")}
            <Badge tone="neutral" icon={<LockIcon />}>
              {f("confidentialBadge")}
            </Badge>
          </span>
        }
        headingId="details-heading"
        description={f("confidentialNotice")}
      >
        {nothing ? (
          <p className="text-ink-soft">{t("noDetails")}</p>
        ) : (
          <DescriptionList>
            {written.map((key) => (
              <Description key={key} label={f(key)}>
                {prose(confidential[key])}
              </Description>
            ))}
            {confidential.links.length > 0 ? (
              <Description label={f("links")}>
                <ul className="flex flex-col gap-1">
                  {confidential.links.map((link) => (
                    <li key={link} className="[overflow-wrap:anywhere]">
                      {link}
                    </li>
                  ))}
                </ul>
              </Description>
            ) : null}
            {confidential.attachments.length > 0 ? (
              <Description label={f("files")}>
                <ul className="flex flex-col gap-1">
                  {confidential.attachments.map((file) => (
                    <li key={file.id} className="[overflow-wrap:anywhere]">
                      {file.file_name}
                      {file.size_bytes !== null ? (
                        <span className="ml-2 text-sm text-ink-soft">{f(fileSizeParts(file.size_bytes).key, { value: fileSizeParts(file.size_bytes).value })}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </Description>
            ) : null}
          </DescriptionList>
        )}
      </Section>
    </Panel>
  );
}

/** Text the owner wrote, with their line breaks kept. */
function prose(text: string | null | undefined): ReactNode {
  return text ? <span className="whitespace-pre-line [overflow-wrap:anywhere]">{text}</span> : null;
}
