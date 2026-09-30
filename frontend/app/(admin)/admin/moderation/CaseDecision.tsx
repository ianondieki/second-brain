"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Chip } from "@/components/tracker/Chip";
import { Button, buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/status-icons";

import type { confirmStepUp } from "../research/calls";
import { StepUp } from "../research/StepUp";
import { decideCase } from "./calls";
import { MODERATION_PATH, refusalNext, type Blocked, type Choice, type RefusalCode } from "./moderation";

type Phase =
  | { kind: "idle" }
  | { kind: "confirmReject" }
  | { kind: "busy"; choice: Choice }
  | { kind: "stepUp"; choice: Choice };

/** What the status line says: a key under adminModeration and its tone (a mark and words, never colour alone). */
type Notice =
  | { tone: "ok"; key: "decision.approvedProposal" | "decision.approvedProblem" | "decision.rejected" }
  | { tone: "info"; key: "decision.changed" }
  | { tone: "error"; key: `refusal.${RefusalCode}` };

export interface CaseDecisionProps {
  caseId: string;
  /** The proposal version the page shows (sent back with the decision); null for problems. */
  versionId: string | null;
  kind: "proposal" | "problem" | "other";
  /** The decisions the API accepts from this moderator now. */
  actions: readonly Choice[];
  blocked: Blocked | null;
  /** A decided case: its outcome and the line saying who decided it and when (formatted on the server). */
  decided: { outcome: "approved" | "rejected"; line: string } | null;
  /** The next case to review after this one, if any. */
  nextHref: string | null;
  decideImpl?: typeof decideCase;
  confirmImpl?: typeof confirmStepUp;
}

const APPROVE_ID = "case-approve";
const REJECT_ID = "case-reject";
const CONFIRM_ID = "case-reject-confirm";
const QUESTION_ID = "case-reject-question";

function focusSoon(id: string) {
  requestAnimationFrame(() => document.getElementById(id)?.focus());
}

const TONE = {
  ok: { Icon: CheckIcon, className: "text-ok" },
  info: { Icon: InfoIcon, className: "text-jacaranda" },
  error: { Icon: AlertIcon, className: "text-error" },
} as const;

/**
 * A moderator's decision on one case (REQ-MOD-01; POST /api/admin/moderation/cases/{case_id}/decision). Approve is
 * the screen's one primary action; Reject asks once more (the question takes focus, Cancel gives it back). The
 * decision carries the version the page shows: when the author has published another since (409 case_changed) the page
 * is fetched again with the new text and the status line says why. Every refusal is a fixed sentence (never the
 * API's words): a case decided meanwhile shows that decision, one that is gone or not this moderator's leaves only the
 * way back, and vulnerability content leaves only Reject. A stale second factor asks for a fresh code, then repeats
 * the decision. The status line stays in the page whatever happens, and takes focus when it changes.
 */
export function CaseDecision({
  caseId,
  versionId,
  kind,
  actions,
  blocked,
  decided,
  nextHref,
  decideImpl = decideCase,
  confirmImpl,
}: CaseDecisionProps) {
  const t = useStrings("adminModeration");
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [notice, setNotice] = useState<Notice | null>(null);
  const [done, setDone] = useState<Choice | null>(null);
  const [after, setAfter] = useState<"back" | "rejectOnly" | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  // Every notice (even the same one again) moves focus to the status line.
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (shown > 0) noticeRef.current?.focus();
  }, [shown]);

  function say(next: Notice) {
    setNotice(next);
    setShown((count) => count + 1);
  }

  async function run(choice: Choice) {
    setPhase({ kind: "busy", choice });
    const outcome = await decideImpl(caseId, choice, versionId);
    if (outcome.ok) {
      setPhase({ kind: "idle" });
      setDone(choice);
      say({
        tone: "ok",
        key:
          choice === "reject"
            ? "decision.rejected"
            : kind === "problem"
              ? "decision.approvedProblem"
              : "decision.approvedProposal",
      });
      router.refresh();
      return;
    }
    const { refusal } = outcome;
    if (refusal.kind === "stepUp") {
      setPhase({ kind: "stepUp", choice });
      return;
    }
    setPhase({ kind: "idle" });
    if (refusal.kind === "changed") {
      say({ tone: "info", key: "decision.changed" });
      router.refresh(); // the new version's text, flags and choices
      return;
    }
    say({ tone: "error", key: `refusal.${refusal.code}` });
    const next = refusalNext(refusal.code);
    if (next) setAfter(next);
    if (refusal.code === "already_decided" || refusal.code === "cannot_approve_vulnerability") router.refresh();
  }

  const region = (
    <div
      ref={noticeRef}
      tabIndex={-1}
      role="status"
      data-notice={notice?.key}
      className={cn("focus:outline-none", notice && "mb-4")}
    >
      {notice ? <NoticeLine tone={notice.tone} text={t(notice.key)} /> : null}
    </div>
  );

  const back = (primary: boolean) => (
    <Link
      href={MODERATION_PATH}
      data-primary={primary ? "" : undefined}
      className={primary ? buttonClass("primary", "no-underline") : standaloneLinkClass}
    >
      {t("decision.back")}
    </Link>
  );

  let body;
  if (done) {
    body = (
      <div className="flex flex-col items-start gap-3">
        {nextHref ? (
          <Link href={nextHref} data-primary="" className={buttonClass("primary", "no-underline")}>
            {t("decision.next")}
          </Link>
        ) : null}
        {back(false)}
      </div>
    );
  } else if (decided) {
    body = (
      <div className="flex flex-col items-start gap-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ink" data-decided={decided.outcome}>
          <Chip kind={decided.outcome === "approved" ? "completed" : "ended"}>
            {t(`outcome.${decided.outcome}`)}
          </Chip>
          <span>{decided.line}</span>
        </p>
        {back(false)}
      </div>
    );
  } else if (after === "back") {
    body = back(true);
  } else if (actions.length === 0) {
    body = (
      <div className="flex flex-col items-start gap-3">
        {blocked ? <NoticeLine tone="info" text={t(`blocked.${blocked}`)} data-blocked={blocked} /> : null}
        {back(false)}
      </div>
    );
  } else if (phase.kind === "stepUp") {
    const choice = phase.choice;
    body = (
      <StepUp
        confirmImpl={confirmImpl}
        onConfirmed={() => run(choice)}
        onCancel={() => {
          setPhase({ kind: "idle" });
          focusSoon(choice === "approve" ? APPROVE_ID : REJECT_ID);
        }}
      />
    );
  } else {
    const canApprove = actions.includes("approve") && after !== "rejectOnly";
    const busy = phase.kind === "busy";
    body = (
      <div className="flex flex-col gap-4">
        {blocked === "cannot_approve_vulnerability" && after !== "rejectOnly" ? (
          <NoticeLine tone="info" text={t("blocked.cannot_approve_vulnerability")} data-blocked={blocked} />
        ) : null}
        {phase.kind === "confirmReject" ? (
          <div
            id={CONFIRM_ID}
            role="group"
            tabIndex={-1}
            aria-labelledby={QUESTION_ID}
            data-confirm="reject"
            className="flex flex-col items-start gap-3 border-l-2 border-error pl-4 focus:outline-none"
          >
            <p id={QUESTION_ID} className="max-w-[60ch] text-ink">
              {kind === "problem" ? t("decision.rejectConfirmProblem") : t("decision.rejectConfirmProposal")}
            </p>
            <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
              <Button variant={canApprove ? "secondary" : "primary"} onClick={() => void run("reject")}>
                {t("decision.rejectYes")}
              </Button>
              <Button
                variant="link"
                onClick={() => {
                  setPhase({ kind: "idle" });
                  focusSoon(REJECT_ID);
                }}
              >
                {t("decision.cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {canApprove ? (
              <Button id={APPROVE_ID} variant="primary" busy={busy} onClick={() => void run("approve")}>
                {busy && phase.choice === "approve" ? t("decision.approving") : t("decision.approve")}
              </Button>
            ) : null}
            <Button
              id={REJECT_ID}
              variant={canApprove ? "secondary" : "primary"}
              busy={busy}
              onClick={() => {
                setPhase({ kind: "confirmReject" });
                focusSoon(CONFIRM_ID);
              }}
            >
              {busy && phase.choice === "reject" ? t("decision.rejecting") : t("decision.reject")}
            </Button>
          </div>
        )}
      </div>
    );
  }

  // The status line is a plain block, empty and without height when there is nothing to say: never display:none or
  // display:contents, which can drop a live region from the accessibility tree.
  return (
    <div className="flex flex-col">
      {region}
      {body}
    </div>
  );
}

function NoticeLine({
  tone,
  text,
  ...rest
}: {
  tone: keyof typeof TONE;
  text: string;
  "data-blocked"?: string;
}) {
  const { Icon, className } = TONE[tone];
  return (
    <p className="flex max-w-[65ch] items-start gap-2 text-ink" {...rest}>
      <Icon className={cn("mt-0.5 size-5 shrink-0", className)} />
      <span>{text}</span>
    </p>
  );
}
