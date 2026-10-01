import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ConfidentialIcon } from "@/components/org-icons";
import { buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";

import { Fingerprint } from "@/app/(public)/verify/Fingerprint";

import { tier2Src, type EvaluationNda, type NdaResult } from "../../data";
import { formatMoment } from "../../format";
import { ACTION_HREF, ownerPreviewHref, REFUSAL_ACTION, type Refusal } from "../../refusals";
import { NdaAccept } from "./NdaAccept";
import { StepUp } from "./StepUp";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export interface FullProposalProps {
  orgId: string;
  orgName: string;
  proposalId: string;
  title: string;
  nda: NdaResult;
  /** ?view=full: the person asked to open the marked page (each opening is a logged view). */
  viewing: boolean;
  hrefs: { here: string; view: string; inbox: string };
}

/**
 * The Tier-2 area under the teaser, behind "the fold": one of four states, each with at most one primary action
 * (REQ-REPO-01, REQ-PROV-03, REQ-SEC-01).
 * 1. refused: the first failing condition as one sentence and at most one action (the step-up is a code form here);
 * 2. the Evaluation NDA: its text, version and SHA-256, the viewer-logging notice verbatim from the API, "Accept and view";
 * 3. accepted: "View full proposal" (opening it is a view, so it never opens by itself);
 * 4. viewing: the marked page in a sandboxed frame through the same-origin /api rewrite (its own CSP; no script).
 */
export async function FullProposal({ orgId, orgName, proposalId, title, nda, viewing, hrefs }: FullProposalProps) {
  const t = await getTranslations("orgProposal");
  let body: ReactNode;
  let open = false;
  if (nda.kind === "refused") {
    body = await RefusalNotice({ refusal: nda.refusal, orgName, proposalId, hrefs });
  } else if (nda.nda.acceptance_id === null) {
    body = await NdaStep({ nda: nda.nda, orgId, orgName, proposalId, hrefs });
  } else if (!viewing) {
    body = await Accepted({ nda: nda.nda, hrefs });
  } else {
    open = true;
    body = (
      <div className="flex flex-col items-start gap-3">
        <p className="max-w-[60ch] text-sm text-ink-soft">{t("viewNote")}</p>
        <iframe
          src={tier2Src(orgId, proposalId)}
          title={t("frameTitle", { title })}
          // No scripts, forms or same-origin access for the page; its links open in a new tab outside the sandbox.
          sandbox="allow-popups allow-popups-to-escape-sandbox"
          referrerPolicy="no-referrer"
          className="h-[70dvh] min-h-96 w-full rounded-control border border-line bg-field lg:h-[80vh]"
          data-tier2-frame=""
        />
        <p className="text-sm text-ink-soft">{t("frameNote")}</p>
        <StandaloneLink href={hrefs.here}>
          {t("close")}
        </StandaloneLink>
      </div>
    );
  }
  return (
    // The fold between the public teaser and the full proposal: the lock, the heading and a hairline running to the
    // column's edge (no coloured left rule under it; the content keeps the page's own left edge).
    <section aria-labelledby="full-proposal" className="mt-6" data-tier2-state={stateName(nda, viewing)}>
      <div className="flex items-center gap-3">
        <ConfidentialIcon open={open} className="size-6 shrink-0 text-accent" />
        <h2 id="full-proposal" className="shrink-0 text-lg text-ink">
          {t("fullHeading")}
        </h2>
        <span aria-hidden="true" className="h-px flex-1 bg-line" />
      </div>
      <div className="mt-6">{body}</div>
    </section>
  );
}

function stateName(nda: NdaResult, viewing: boolean) {
  if (nda.kind === "refused") return "refused";
  if (nda.nda.acceptance_id === null) return "nda";
  return viewing ? "viewing" : "accepted";
}

async function RefusalNotice({
  refusal,
  orgName,
  proposalId,
  hrefs,
}: {
  refusal: Refusal;
  orgName: string;
  proposalId: string;
  hrefs: FullProposalProps["hrefs"];
}) {
  const t = await getTranslations("orgProposal");
  const action = REFUSAL_ACTION[refusal];
  if (action === "stepUp") return <StepUp />;
  // Second-factor steps are the screen's one primary action; "Try again" re-fetches this page (a plain link, no script).
  const primary = action === "enterCode" || action === "turnOnMfa";
  const href =
    action === "inbox"
      ? hrefs.inbox
      : action === "reload" || action === "newVersion"
        ? hrefs.here
        : action
          ? ACTION_HREF[action]
          : undefined;
  const sentence = <p className="max-w-[60ch] text-ink">{t(`refusal.${refusal}`, { org: orgName })}</p>;
  if (action === "ownerPreview") {
    // A plain anchor, not <Link>: the preview is the API's page, and a prefetch would read (and audit) it.
    return (
      <div className="flex flex-col items-start gap-3" data-refusal={refusal}>
        {sentence}
        <a href={ownerPreviewHref(proposalId)} className={standaloneLinkClass}>
          {t("action.ownerPreview")}
        </a>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-3" data-refusal={refusal}>
      {sentence}
      {action && href ? (
        <Link
          href={href}
          className={primary ? buttonClass("primary", "no-underline") : standaloneLinkClass}
          {...(primary ? { "data-primary": "" } : {})}
        >
          {t(`action.${action}`)}
        </Link>
      ) : null}
    </div>
  );
}

async function NdaStep({
  nda,
  orgId,
  orgName,
  proposalId,
  hrefs,
}: {
  nda: EvaluationNda;
  orgId: string;
  orgName: string;
  proposalId: string;
  hrefs: FullProposalProps["hrefs"];
}) {
  const t = await getTranslations("orgProposal");
  return (
    <div className="flex flex-col items-start gap-5">
      <div>
        <h3 className="text-base font-semibold text-ink">{t("ndaHeading")}</h3>
        <p className="mt-1 max-w-[60ch] text-ink">{t("ndaLead", { org: orgName })}</p>
      </div>
      <div className="w-full max-w-2xl rounded-control border border-line bg-field">
        <div
          role="region"
          tabIndex={0}
          aria-label={t("ndaTextLabel", { version: nda.version })}
          className="max-h-72 overflow-y-auto px-4 py-4 whitespace-pre-wrap [overflow-wrap:anywhere] text-ink sm:px-5"
          data-nda-body=""
        >
          {nda.body}
        </div>
        <dl className="flex flex-col gap-2 border-t border-line px-4 py-3 text-sm sm:px-5">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-ink-soft">{t("ndaVersionLabel")}</dt>
            <dd className="font-semibold text-ink" data-nda-version={nda.version}>
              {nda.version}
            </dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-ink-soft">{t("ndaFingerprint")}</dt>
            <dd>
              <Fingerprint hex={nda.sha256} className="text-sm leading-6" />
            </dd>
          </div>
        </dl>
      </div>
      {nda.is_placeholder ? <p className="max-w-[60ch] text-sm text-ink-soft">{t("ndaDraft")}</p> : null}
      <div className="max-w-[60ch]">
        <h3 className="text-base font-semibold text-ink">{t("noticeHeading")}</h3>
        {/* The viewer-logging notice exactly as the API sends it (its version is echoed on acceptance). */}
        <p className="mt-1 text-ink" data-logging-notice={nda.logging_notice.version}>
          {nda.logging_notice.text}
        </p>
      </div>
      <NdaAccept
        key={`${nda.template_id}:${nda.sha256}:${nda.logging_notice.version}`}
        orgId={orgId}
        proposalId={proposalId}
        templateId={nda.template_id}
        sha256={nda.sha256}
        noticeVersion={nda.logging_notice.version}
        viewHref={hrefs.view}
        inboxHref={hrefs.inbox}
        orgName={orgName}
      />
    </div>
  );
}

async function Accepted({ nda, hrefs }: { nda: EvaluationNda; hrefs: FullProposalProps["hrefs"] }) {
  const t = await getTranslations("orgProposal");
  const locale = await getLocale();
  return (
    <div className="flex flex-col items-start gap-4">
      <p className="max-w-[60ch] text-ink">
        {t("accepted", { version: nda.version, date: formatMoment(locale, nda.accepted_at!) })}
      </p>
      <p className="max-w-[60ch] text-sm text-ink-soft">{t("viewNote")}</p>
      <ButtonLink href={hrefs.view} variant="primary">
        {t("view")}
      </ButtonLink>
    </div>
  );
}
