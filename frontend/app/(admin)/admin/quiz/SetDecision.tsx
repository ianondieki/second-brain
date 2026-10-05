"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { StepUp } from "../research/StepUp";
import { adminQuizCalls, type AdminQuizCalls, type Decision } from "./calls";
import { refusalNext, type RefusalCode } from "./quiz";

export interface SetDecisionProps {
  setId: string;
  /** The set's day as the page writes it ("6 Oct 2026"). */
  day: string;
  calls?: AdminQuizCalls;
}

/**
 * The staff admin's decision on a draft set (REQ-DEV-01; POST /api/admin/quiz/sets/{id}/decision): "Approve" is the
 * screen's one primary action, "Reject" the other; each asks once more in a dialog that says what follows. A stale
 * second factor asks for a fresh code in place, then repeats the decision. A day that is over can only be rejected:
 * Reject becomes the primary action and Approve stays but is inert. Done: one sentence, and the page is fetched again.
 */
export function SetDecision({ setId, day, calls: given }: SetDecisionProps) {
  const t = useStrings("adminQuiz");
  const router = useRouter();
  const calls = useRef(given ?? adminQuizCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const notice = useRef<HTMLDivElement>(null);
  const [choice, setChoice] = useState<Decision>("approve");
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [refusal, setRefusal] = useState<RefusalCode | null>(null);
  const [done, setDone] = useState<Decision | null>(null);

  useEffect(() => {
    if (refusal || done) notice.current?.focus();
  }, [refusal, done]);

  const final = refusal !== null && refusalNext(refusal) === "reject";

  async function run(decision: Decision) {
    setBusy(true);
    setRefusal(null);
    const outcome = await calls.decide(setId, decision);
    setBusy(false);
    dialog.current?.close();
    if (outcome.ok) {
      setStepUp(false);
      setDone(decision);
      router.refresh();
      return;
    }
    if (outcome.refusal.kind === "stepUp") {
      setStepUp(true);
      return;
    }
    setStepUp(false);
    setRefusal(outcome.refusal.code);
    if (refusalNext(outcome.refusal.code) === "reload") router.refresh();
  }

  function ask(decision: Decision) {
    if (busy || (decision === "approve" && final)) return;
    setChoice(decision);
    openConfirm(dialog.current);
  }

  if (done) {
    return (
      <Alert tone="ok" ref={notice}>
        <p data-decision={done}>{done === "approve" ? t("decision.approved", { date: day }) : t("decision.rejected")}</p>
      </Alert>
    );
  }

  if (stepUp) {
    return (
      <StepUp
        onConfirmed={() => run(choice)}
        onCancel={() => {
          setStepUp(false);
          requestAnimationFrame(() => document.getElementById(`decision-${choice}`)?.focus());
        }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {refusal ? (
        <Alert ref={notice}>
          <p data-refusal={refusal}>{t(`refusal.${refusal}`)}</p>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button
          id="decision-approve"
          variant={final ? "secondary" : "primary"}
          busy={busy}
          aria-disabled={busy || final || undefined}
          onClick={() => ask("approve")}
        >
          {t("decision.approve")}
        </Button>
        <Button id="decision-reject" variant={final ? "primary" : "secondary"} busy={busy} onClick={() => ask("reject")}>
          {t("decision.reject")}
        </Button>
      </div>
      <ConfirmDialog
        ref={dialog}
        title={choice === "approve" ? t("decision.approveTitle") : t("decision.rejectTitle")}
        confirmLabel={choice === "approve" ? t("decision.approve") : t("decision.reject")}
        busyLabel={choice === "approve" ? t("decision.approving") : t("decision.rejecting")}
        busy={busy}
        tone={choice === "approve" ? "primary" : "danger"}
        cancelLabel={t("decision.cancel")}
        onConfirm={() => void run(choice)}
      >
        <p>{choice === "approve" ? t("decision.approveBody", { date: day }) : t("decision.rejectBody", { date: day })}</p>
      </ConfirmDialog>
    </div>
  );
}
