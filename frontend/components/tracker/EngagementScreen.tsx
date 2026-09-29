import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";
import { clientStrings } from "@/lib/i18n/client-strings";
import type { Me } from "@/lib/auth/routing";

import { Actions } from "./Actions";
import { ContactReveal } from "./ContactReveal";
import { engagementDocument, engagementHistory, orgMembers } from "./data";
import { Agreements, ContactPerson, Payments, Signatures } from "./Deal";
import { Endorsements } from "./Endorsements";
import { HistoryList } from "./HistoryList";
import {
  actionItems,
  DOCUMENT_KINDS,
  documentKinds,
  DUAL_ENDORSEMENT_STATES,
  isFinished,
  kesAmount,
  shortHash,
  stageLeft,
  stepperSteps,
  type Detail,
  type DocumentKind,
} from "./model";
import { Stepper } from "./Stepper";
import { DueText } from "./When";
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
}

/**
 * One engagement's tracker, the same for both parties (docs/spec/06 6.9; AC-TRACK-3): the whose-turn banner, the
 * 5-group stepper, the caller's buttons (from the API's `actions` only), then the Tracker, Documents and History tabs.
 * Only the buttons and the contact reveal differ between the developer and the organisation.
 */
export async function EngagementScreen({ detail, me, tab, doc, basePath }: EngagementScreenProps) {
  const t = await getTranslations("tracker");
  const locale = await getLocale();
  const finished = isFinished(detail.state) && detail.state !== "CLOSED";
  // An ended or paused engagement has no stage group: its history says which stage it left.
  const history =
    tab === "history" || (finished || detail.stage_group === null) ? await engagementHistory(detail.id) : null;
  const steps = stepperSteps({ ...detail, left: stageLeft(detail.state, history?.events) });
  const href = `${basePath}/${encodeURIComponent(detail.id)}`;
  const items = actionItems(detail);
  const members = detail.actions.includes("approve") ? await orgMembers(detail.org_id) : undefined;
  const finalPayment = detail.payments.find((p) => p.milestone_id === null) ?? null;
  const counterpart = detail.my_party === "developer" ? detail.org_name : detail.developer_name;

  return (
    <ClientStrings strings={await clientStrings(["trackerActions"])}>
      <p className="-mt-2 mb-4">
        <Link href={basePath} className={standaloneLinkClass}>
          {t("back")}
        </Link>
      </p>
      <h1 className="max-w-3xl text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">{detail.proposal_title}</h1>
      <p className="mt-2 text-ink-soft [overflow-wrap:anywhere]">
        {detail.my_party === "developer"
          ? t("withOrg", { org: detail.org_name })
          : t("fromDeveloper", { name: detail.developer_name })}
      </p>

      <div className="mt-6 max-w-3xl">
        <WhoseTurn detail={detail} />
      </div>

      <div className="mt-8">
        <Stepper
          steps={steps}
          detail={
            <>
              <span className="block font-semibold">{t("stageNow", { stage: detail.stage_label })}</span>
              {detail.due && !isFinished(detail.state) ? (
                <DueText due={detail.due} className={detail.due.overdue ? "font-semibold text-error" : "text-ink-soft"} />
              ) : null}
            </>
          }
        />
      </div>

      <div className="mt-8 max-w-3xl">
        <Actions
            engagementId={detail.id}
            lockVersion={detail.lock_version}
            items={items}
            counterpart={counterpart}
            enrolled={me.mfa.enrolled}
            members={members}
            myUserId={me.user.id}
            recorded={finalPayment ? kesAmount(finalPayment.amount_kes_minor, locale) : null}
          />
      </div>

      <nav aria-label={t("tabs.label")} className="mt-10 max-w-3xl border-b border-line">
        <ul className="flex gap-1 overflow-x-auto">
          {TABS.map((name) => (
            <li key={name}>
              <Link
                href={name === "tracker" ? href : `${href}?tab=${name}`}
                aria-current={name === tab ? "page" : undefined}
                className={cn(
                  "-mb-px inline-flex min-h-11 items-center border-b-2 px-3 font-semibold no-underline",
                  name === tab ? "border-jacaranda text-jacaranda" : "border-transparent text-ink-soft hover:text-ink",
                )}
              >
                {t(`tabs.${name}`)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-6 flex max-w-3xl flex-col gap-10">
        {tab === "tracker" ? <TrackerTab detail={detail} me={me} /> : null}
        {tab === "documents" ? <DocumentsTab detail={detail} doc={doc} href={href} /> : null}
        {tab === "history" && history ? <HistoryList history={history} /> : null}
      </div>
    </ClientStrings>
  );
}

async function TrackerTab({ detail, me }: { detail: Detail; me: Me }) {
  const t = await getTranslations("tracker");
  const dual = DUAL_ENDORSEMENT_STATES.has(detail.state) || detail.endorsements.some((e) => e.milestone_id === null);
  const namedContact = detail.my_party === "org" && detail.contact?.user_id === me.user.id;
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

async function DocumentsTab({ detail, doc, href }: { detail: Detail; doc: DocumentKind | null; href: string }) {
  const t = await getTranslations("tracker");
  const kinds = documentKinds(detail);
  if (kinds.length === 0) {
    return (
      <div data-empty-state="" className="flex flex-col items-start gap-3">
        <p className="text-ink">{t("documents.empty")}</p>
        <Link href={href} className={standaloneLinkClass}>
          {t("documents.emptyAction")}
        </Link>
      </div>
    );
  }
  const shown = doc && kinds.includes(doc) ? doc : kinds[0];
  const text = await engagementDocument(detail.id, shown);
  return (
    <section aria-labelledby="documents-heading">
      <h2 id="documents-heading" className="text-lg text-ink">
        {t("documents.title")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t("documents.lead")}</p>
      <ul className="mt-3 flex flex-wrap gap-x-5">
        {kinds.map((kind) => (
          <li key={kind}>
            <Link
              href={`${href}?tab=documents&doc=${kind}`}
              aria-current={kind === shown ? "page" : undefined}
              className={cn(standaloneLinkClass, kind === shown && "text-ink no-underline")}
            >
              {t(`document.${kind}`)}
            </Link>
          </li>
        ))}
      </ul>
      {text ? (
        <article data-document={text.kind} className="mt-4 border-t border-line pt-4">
          <h3 className="font-semibold text-ink">{t(`document.${text.kind}`)}</h3>
          <p
            className={cn(
              "mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm font-medium",
              text.intact ? "text-ok" : "text-error",
            )}
          >
            <span className="inline-flex items-center gap-1.5">
              {text.intact ? <CheckIcon className="size-4" /> : <AlertIcon className="size-4" />}
              {text.intact ? t("documents.intact") : t("documents.changed")}
            </span>
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
    </section>
  );
}
