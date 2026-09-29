import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DevNav } from "@/components/DevNav";
import { IntlScope } from "@/components/IntlScope";
import { SignedInShell } from "@/components/SignedInShell";
import { Alert, type AlertTone } from "@/components/ui/Alert";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { cn } from "@/components/ui/cn";
import { CheckIcon, ClockIcon, LockIcon } from "@/components/ui/icons";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

import { countyName, myIdea } from "../data";
import {
  BASE_PATH,
  editHref,
  MATURITY_KEY,
  type MyProposal,
  type Version,
} from "../ideas";
import { formatMoment } from "../dates";
import { fileSizeParts } from "../files";
import { ideaStatus, type IdeaStatus } from "../status";
import { IdeaStatusBadge } from "../IdeaStatusBadge";
import { DeleteIdea } from "./DeleteIdea";

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
 * full details (yours only), and the certificate with its /verify link and PDF. "Edit idea" (or "Continue editing")
 * is the one primary action; a hidden idea has none, since it cannot change.
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
        <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
        <div data-empty-state="" className="mt-6 border-t border-line pt-6">
          <p className="text-ink">{t("notFound")}</p>
          <Link href={BASE_PATH} className={standaloneLinkClass}>
            {t("back")}
          </Link>
        </div>
      </SignedInShell>
    );
  }

  const status = ideaStatus(idea.status, idea.moderation.state);
  const version = shownVersion(idea);
  const hasChanges = idea.current !== null && idea.draft !== null;
  const notice = noticeFor(status, hasChanges);

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />}>
      <p className="-mt-2 mb-4">
        <Link href={BASE_PATH} className={standaloneLinkClass}>
          {t("back")}
        </Link>
      </p>
      <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
        {version?.teaser.title?.trim() || t("untitled")}
      </h1>
      <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
        <IdeaStatusBadge status={status} />
        {idea.current ? (
          <span className="text-ink-soft">{t("version", { number: idea.current.version_no })}</span>
        ) : null}
      </p>

      {justPublished && idea.current?.cert_id ? (
        <Alert tone="ok" className="mt-6">
          {t("published", { certId: idea.current.cert_id })}
        </Alert>
      ) : null}
      {notice ? (
        <Alert tone={notice.tone} className="mt-6">
          {t(notice.key)}
        </Alert>
      ) : null}

      {status !== "hidden" ? (
        <div className="mt-6">
          <ButtonLink href={editHref(idea.id)} variant="primary">
            {idea.draft ? t("continueDraft") : t("edit")}
          </ButtonLink>
        </div>
      ) : null}

      {version ? <Teaser version={version} status={status} /> : null}
      {version ? <Confidential version={version} /> : null}
      <Certificate idea={idea} />

      {/* P3: "Who has seen this" (REQ-PROP-03) goes here. P4: "Pitch to companies" (REQ-REPO-01) goes here. */}

      {status !== "hidden" ? (
        <section className="mt-12 border-t border-line pt-6">
          <IntlScope namespaces={["ideaDelete"]}>
            <DeleteIdea id={idea.id} registered={idea.current !== null} />
          </IntlScope>
        </section>
      ) : null}
    </SignedInShell>
  );
}

type NoticeKey = "heldNotice" | "rejectedNotice" | "hiddenNotice" | "changesNotice" | "draftNotice";

function noticeFor(status: IdeaStatus, hasChanges: boolean): { key: NoticeKey; tone: AlertTone } | null {
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

async function Teaser({ version, status }: { version: Version; status: IdeaStatus }) {
  const f = await getTranslations("ideaFields");
  const { teaser } = version;
  const empty = <span className="text-ink-soft">{f("notGiven")}</span>;
  return (
    <section aria-labelledby="teaser-heading" className="mt-10">
      <h2 id="teaser-heading" className="text-lg text-ink">
        {f("teaserTitle")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{f(TEASER_HINT[status])}</p>
      <dl className="mt-4 grid gap-x-8 gap-y-4 border-t border-line pt-5 sm:grid-cols-[minmax(9rem,auto)_1fr]">
        <Row label={f("niche")}>{teaser.niche?.label ?? empty}</Row>
        <Row label={f("maturity")}>{teaser.maturity ? f(`maturityValue.${MATURITY_KEY[teaser.maturity]}`) : empty}</Row>
        <Row label={f("ask")}>{teaser.ask ? f(`askValue.${teaser.ask}`) : empty}</Row>
        <Row label={f("problems")}>
          {version.problems.length > 0 || version.new_problem ? (
            <ul className="flex flex-col gap-1">
              {version.problems.map((problem) => (
                <li key={problem.id}>
                  {problem.title}
                  {problem.source === "developer" ? (
                    <span className="ml-2 text-sm text-ink-soft">{f("developerReported")}</span>
                  ) : null}
                </li>
              ))}
              {version.new_problem ? (
                <li>
                  {version.new_problem.title}
                  <span className="ml-2 text-sm text-ink-soft">{f("developerReported")}</span>
                </li>
              ) : null}
            </ul>
          ) : (
            empty
          )}
        </Row>
        <Row label={f("problemStatement")}>{prose(teaser.problem_statement) ?? empty}</Row>
        <Row label={f("summary")}>{prose(teaser.summary) ?? empty}</Row>
        {teaser.impact_claims ? <Row label={f("impactClaims")}>{prose(teaser.impact_claims)}</Row> : null}
        {teaser.county_code ? <Row label={f("county")}>{await countyName(teaser.county_code)}</Row> : null}
      </dl>
    </section>
  );
}

async function Confidential({ version }: { version: Version }) {
  const f = await getTranslations("ideaFields");
  const t = await getTranslations("ideas");
  const { confidential } = version;
  const written = (["approach", "architecture", "pricing", "notes"] as const).filter((key) => confidential[key]);
  const nothing = written.length === 0 && confidential.links.length === 0 && confidential.attachments.length === 0;
  return (
    <section aria-labelledby="details-heading" className="mt-10 border-l-4 border-jacaranda pl-4 sm:pl-6">
      <h2 id="details-heading" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-lg text-ink">
        {f("confidentialTitle")}
        <span className="inline-flex items-center gap-1 text-sm font-semibold tracking-normal text-jacaranda">
          <LockIcon className="size-4" />
          {f("confidentialBadge")}
        </span>
      </h2>
      <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{f("confidentialNotice")}</p>
      {nothing ? (
        <p className="mt-4 text-ink-soft">{t("noDetails")}</p>
      ) : (
        <dl className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-[minmax(9rem,auto)_1fr]">
          {written.map((key) => (
            <Row key={key} label={f(key)}>
              {prose(confidential[key])}
            </Row>
          ))}
          {confidential.links.length > 0 ? (
            <Row label={f("links")}>
              <ul className="flex flex-col gap-1">
                {confidential.links.map((link) => (
                  <li key={link} className="[overflow-wrap:anywhere]">
                    {link}
                  </li>
                ))}
              </ul>
            </Row>
          ) : null}
          {confidential.attachments.length > 0 ? (
            <Row label={f("files")}>
              <ul className="flex flex-col gap-1">
                {confidential.attachments.map((file) => (
                  <li key={file.id} className="[overflow-wrap:anywhere]">
                    {file.file_name}
                    {file.size_bytes !== null ? (
                      <span className="ml-2 text-sm text-ink-soft">{f("fileSize", fileSizeParts(file.size_bytes))}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Row>
          ) : null}
        </dl>
      )}
    </section>
  );
}

async function Certificate({ idea }: { idea: MyProposal }) {
  const t = await getTranslations("ideas");
  const locale = await getLocale();
  const current = idea.current;
  const certId = current?.cert_id;
  const stamped = current?.provenance?.status === "timestamped";
  return (
    <section aria-labelledby="certificate-heading" className="mt-10">
      <h2 id="certificate-heading" className="text-lg text-ink">
        {t("certificateTitle")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t("certificateLead")}</p>
      {current && certId ? (
        <>
          <dl className="mt-4 grid gap-x-8 gap-y-4 border-t border-line pt-5 sm:grid-cols-[minmax(9rem,auto)_1fr]">
            <Row label={t("certificateId")}>
              <span className="font-semibold tracking-[0.06em] tabular-nums [overflow-wrap:anywhere]">{certId}</span>
            </Row>
            {current.registered_at ? (
              <Row label={t("registered")}>
                {t("registeredAt", { time: formatMoment(locale, current.registered_at) })}
              </Row>
            ) : null}
            <Row label={t("evidenceStatus")}>
              <span className={cn("inline-flex items-center gap-1.5 font-medium", stamped ? "text-ok" : "text-ink")}>
                {stamped ? <CheckIcon className="size-5 shrink-0" /> : <ClockIcon className="size-5 shrink-0" />}
                {stamped ? t("timestamped") : t("timestampPending")}
              </span>
            </Row>
          </dl>
          <ul className="mt-4 flex flex-col">
            <li>
              <Link href={`/verify/${encodeURIComponent(certId)}`} className={standaloneLinkClass}>
                {t("verifyLink")}
              </Link>
            </li>
            <li>
              {stamped ? (
                // A plain link: the API answers with the PDF as an attachment (generated on demand, never stored).
                <a
                  href={`/api/provenance/certificates/${encodeURIComponent(certId)}/certificate.pdf`}
                  download
                  className={standaloneLinkClass}
                >
                  {t("download")}
                </a>
              ) : (
                <p className="py-2.5 text-ink-soft">{t("downloadLater")}</p>
              )}
            </li>
          </ul>
        </>
      ) : (
        <p className="mt-4 border-t border-line pt-5 text-ink-soft">{t("noCertificate")}</p>
      )}
    </section>
  );
}

/** Text the owner wrote, with their line breaks kept. */
function prose(text: string | null | undefined): ReactNode {
  return text ? <span className="whitespace-pre-line [overflow-wrap:anywhere]">{text}</span> : null;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-sm font-medium text-ink-soft sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </div>
  );
}
