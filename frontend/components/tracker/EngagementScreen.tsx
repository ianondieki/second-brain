import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { cookies } from "next/headers";

import { celebrationSeenFromCookies } from "@/components/tracker/celebration-store";
import { ClosedCelebration } from "@/components/tracker/ClosedCelebration";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Section } from "@/components/ui/Section";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";
import { LinkPending } from "@/components/ui/LinkPending";
import { TabNav } from "@/components/ui/TabNav";
import { clientStrings } from "@/lib/i18n/client-strings";
import { formatDay } from "@/lib/format";
import type { Me } from "@/lib/auth/routing";

import { Actions } from "./Actions";
import { documentLinkClass } from "./document-link";
import { ContactReveal } from "./ContactReveal";
import { engagementDocument, engagementHistory, orgMembers } from "./data";
import { Agreements, ContactPerson, Payments, Signatures } from "./Deal";
import { Endorsements } from "./Endorsements";
import { HistoryList } from "./HistoryList";
import {
  actionItems,
  counterpartLine,
  DOCUMENT_KINDS,
  documentKinds,
  DUAL_ENDORSEMENT_STATES,
  isFinished,
  formatDate,
  kesAmount,
  offersContactReveal,
  shortHash,
  sideBanner,
  stageLeft,
  stepperSteps,
  type Detail,
  type DocumentKind,
  withQuery,
} from "./model";
import { Stepper } from "./Stepper";
import { Tier2Section } from "./Tier2Section";
import { WhoseTurn } from "./WhoseTurn";

export const TABS = ["tracker", "documents", "history"] as const;
export type Tab = (typeof TABS)[number];


export function asTab(value: string | string[] | undefined): Tab {
  const first = Array.isArray(value) ? value[0] : value;
  return (TABS as readonly string[]).includes(first ?? "") ? (first as Tab) : "tracker";
}

export function asDocumentKind(value: string | string[] | undefined): DocumentKind | null {
  const first = Array.isArray(value) ? value[0] : value;
  return (DOCUMENT_KINDS as readonly string[]).includes(first ?? "") ? (first as DocumentKind) : null;
}

export interface EngagementScreenProps {
  detail: Detail;
  me: Me;
  tab: Tab;
  doc: DocumentKind | null;
  /** "/dev/engagements" or "/org/engagements". */
  basePath: string;
  /** "?org=<id>" when an organisation member of several chose one (kept on every link), else "". */
  query?: string;
}


/**
 * One engagement's tracker, the same for both parties (docs/spec/06 6.9; AC-TRACK-3): the whose-turn banner, the
 * 5-group stepper, the caller's buttons (from the API's `actions` only), then the Tracker, Documents and History tabs.
 * Only the buttons and the contact reveal differ between the developer and the organisation.
 */
export async function EngagementScreen({ detail, me, tab, doc, basePath, query = "" }: EngagementScreenProps) {
  const t = await getTranslations("tracker");
  const locale = await getLocale();
  const finished = isFinished(detail.state) && detail.state !== "CLOSED";
  // An ended engagement has no stage group: its history says which stage it left (a paused one has `paused_from`).
  // The history and, for an approver, the organisation's members are read together.
  const [history, members] = await Promise.all([
    tab === "history" || finished || (detail.stage_group === null && !detail.paused_from)
      ? engagementHistory(detail.id)
      : null,
    detail.actions.includes("approve") ? orgMembers(detail.org_id) : undefined,
  ]);
  const steps = stepperSteps({ ...detail, left: stageLeft(detail.state, history?.events) });
  const href = `${basePath}/${encodeURIComponent(detail.id)}`;
  const items = actionItems(detail);
  const finalPayment = detail.payments.find((p) => p.milestone_id === null) ?? null;
  // The side state's facts the sheets quote: the open question (answer_info) and a hold's end (resume).
  const side = sideBanner(detail);
  const question =
    side?.kind === "info" && side.question ? { body: side.question.body, date: formatDay(locale, side.question.at) } : null;
  const holdEnd = side?.kind === "hold" ? (side.hold?.resume_at ?? detail.due?.due_on ?? null) : null;
  const counterpart = detail.my_party === "developer" ? detail.org_name : detail.developer_name;
  const line = counterpartLine(detail);
  // The party who acts now: the developer, the organisation, or both (the tracker's timeline shows them at the step).
  const awaited = new Set(detail.whose_turn);
  const actors = isFinished(detail.state) ? null : (
    <span className="flex shrink-0 items-center gap-1">
      {awaited.has("developer") ? <Avatar name={detail.developer_name} kind="person" size="sm" active /> : null}
      {awaited.has("org") ? <Avatar name={detail.org_name} kind="org" size="sm" active /> : null}
    </span>
  );

  return (
    <ClientStrings strings={await clientStrings(["trackerActions"])}>
      <PageHeader
        className="max-w-3xl"
        back={{ href: withQuery(basePath, query), label: t("back") }}
        title={detail.proposal_title}
        lead={<span data-counterpart={line.key}>{t(line.key, line.values)}</span>}
      />

      <div className="mt-6 max-w-3xl">
        <WhoseTurn detail={detail} />
      </div>
      {/* The one-time celebration of a closed engagement, drawn on the server; the cookie says whether it was seen. */}
      {detail.state === "CLOSED" ? (
        <ClosedCelebration
          engagementId={detail.id}
          initialSeen={celebrationSeenFromCookies(await cookies(), detail.id)}
          title={t("closed.title")}
          body={t("closed.body")}
          dismiss={t("closed.dismiss")}
        />
      ) : null}

      {/* The one progress indicator: the timeline itself (completed connectors in the accent). On phones the actions
          card comes first, so the screen's primary action is within reach; the timeline follows it. */}
      <div className="mt-6 flex flex-col gap-8">
      <div className="order-2 lg:order-1">
        <Stepper
          steps={steps}
          actor={actors}
          detail={
            <>
              {/* On hold the chip already says it: no "Now: On hold" under "On hold". */}
              {detail.state === "ON_HOLD" ? null : (
                <span className="block font-semibold">{t("stageNow", { stage: detail.stage_label })}</span>
              )}
              {!isFinished(detail.state) ? (
                <span className="block text-ink-soft lg:hidden">{t("since", { date: formatDay(locale, detail.stage_entered_at) })}</span>
              ) : null}
            </>
          }
        />
      </div>

      {/* Actions stays mounted whatever is left to do (it keeps its own "Done" status and focus after a refresh);
          the card frame is drawn only while there is something to do, so a closed or ended engagement draws no
          empty box. */}
      <Card as="div" variant={items.length > 0 ? "raised" : "bare"} padding={items.length > 0 ? "md" : "none"} className="order-1 max-w-3xl has-[>div:empty]:hidden lg:order-2">
        <Actions
          engagementId={detail.id}
          lockVersion={detail.lock_version}
          items={items}
          counterpart={counterpart}
          enrolled={me.mfa.enrolled}
          members={members}
          myUserId={me.user.id}
          recorded={finalPayment ? kesAmount(finalPayment.amount_kes_minor, locale) : null}
          question={question}
          resumeOn={holdEnd ? formatDate(holdEnd, locale) : null}
          locale={locale}
          today={detail.today ?? null}
          limits={detail.side_limits}
        />
      </Card>
      </div>

      <div className="mt-8 max-w-3xl empty:hidden">
        <Tier2Section detail={detail} enrolled={me.mfa.enrolled} query={query} />
      </div>

      <TabNav
        label={t("tabs.label")}
        current={tab}
        className="mt-10 max-w-3xl"
        items={TABS.map((name) => ({
          key: name,
          label: t(`tabs.${name}`),
          href: withQuery(href, query, name === "tracker" ? {} : { tab: name }),
        }))}
      />

      <div className="mt-6 flex max-w-3xl flex-col gap-10">
        {tab === "tracker" ? <TrackerTab detail={detail} me={me} /> : null}
        {tab === "documents" ? <DocumentsTab detail={detail} doc={doc} href={href} query={query} /> : null}
        {tab === "history" && history ? <HistoryList history={history} notes={detail.notes} /> : null}
      </div>
    </ClientStrings>
  );
}

async function TrackerTab({ detail, me }: { detail: Detail; me: Me }) {
  const t = await getTranslations("tracker");
  const dual = DUAL_ENDORSEMENT_STATES.has(detail.state) || detail.endorsements.some((e) => e.milestone_id === null);
  const namedContact = offersContactReveal(detail, me.user.id);
  const nothing =
    !dual && !detail.contact && detail.agreements.length === 0 && detail.signatures.length === 0 && detail.payments.length === 0;
  return (
    <>
      {dual ? <Endorsements detail={detail} /> : null}
      {detail.contact ? (
        <div className="flex flex-col gap-4">
          <ContactPerson detail={detail} />
          {namedContact ? <ContactReveal engagementId={detail.id} /> : null}
        </div>
      ) : null}
      <Agreements detail={detail} />
      <Signatures signatures={detail.signatures} />
      <Payments payments={detail.payments} />
      {nothing ? <p className="text-ink-soft">{t("nothingYet")}</p> : null}
    </>
  );
}

async function DocumentsTab({
  detail,
  doc,
  href,
  query,
}: {
  detail: Detail;
  doc: DocumentKind | null;
  href: string;
  query: string;
}) {
  const t = await getTranslations("tracker");
  const kinds = documentKinds(detail);
  if (kinds.length === 0) {
    return (
      <EmptyState
        rule={false}
        sentence={t("documents.empty")}
        action={t("documents.emptyAction")}
        href={withQuery(href, query)}
      />
    );
  }
  const shown = doc && kinds.includes(doc) ? doc : kinds[0];
  const text = await engagementDocument(detail.id, shown);
  return (
    <Section title={t("documents.title")} headingId="documents-heading" description={t("documents.lead")}>
      <ul className="flex flex-wrap gap-x-5">
        {kinds.map((kind) => (
          <li key={kind}>
            <Link
              href={withQuery(href, query, { tab: "documents", doc: kind })}
              aria-current={kind === shown ? "page" : undefined}
              className={documentLinkClass(kind === shown)}
            >
              {t(`document.${kind}`)}
              <LinkPending className="ml-2" />
            </Link>
          </li>
        ))}
      </ul>
      {text ? (
        <article data-document={text.kind} className="mt-6">
          <h3 className="font-semibold text-ink">{t(`document.${text.kind}`)}</h3>
          <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <Badge tone={text.intact ? "ok" : "error"} icon={text.intact ? <CheckIcon /> : <AlertIcon />}>
              {text.intact ? t("documents.intact") : t("documents.changed")}
            </Badge>
            <span className="text-ink-soft tabular-nums">{t("fingerprint", { hash: shortHash(text.sha256) })}</span>
          </p>
          <div
            tabIndex={0}
            role="region"
            aria-label={t(`document.${text.kind}`)}
            className="mt-4 max-h-[32rem] overflow-y-auto rounded-control border border-line bg-field p-4 text-sm whitespace-pre-wrap text-ink [overflow-wrap:anywhere]"
          >
            {text.text}
          </div>
        </article>
      ) : (
        <p className="mt-4 text-ink-soft">{t("documents.missing")}</p>
      )}
    </Section>
  );
}
