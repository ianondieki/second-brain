"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { StepUp } from "../research/StepUp";
import { adminEventCalls, type AdminEventCalls } from "./calls";
import { decisionNext, type Decision, type DecisionRefusal } from "./events";

type RefusalCode = Extract<DecisionRefusal, { kind: "refusal" }>["code"];

export interface EventDecisionProps {
  eventId: string;
  /** The event's updated_at exactly as the page read it: the version this decision is about. */
  seen: string;
  calls?: AdminEventCalls;
}

/**
 * The staff decision on a draft event (REQ-DEV-02; D-60): "Publish" is the screen's one primary action, "Reject" the
 * other; each asks once more in a dialog that says what follows, then sends the version the page read. A stale second
 * factor asks for a fresh code in place, then repeats the decision. The event changed, or was decided, meanwhile: the
 * sentence says so and the page is read again (its new version is what the next decision sends). An event that is over,
 * or whose organisation can no longer publish, can only be rejected: Reject becomes the primary action and Publish
 * stays but is inert. Done: one sentence, and the page is read again.
 */
export function EventDecision({ eventId, seen, calls: given }: EventDecisionProps) {
  const t = useStrings("adminEvents");
  const tf = useStrings("eventForm");
  const router = useRouter();
  const calls = useRef(given ?? adminEventCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const notice = useRef<HTMLDivElement>(null);
  const [choice, setChoice] = useState<Decision>("publish");
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [refusal, setRefusal] = useState<RefusalCode | null>(null);
  const [done, setDone] = useState<Decision | null>(null);

  useEffect(() => {
    if (refusal || done) notice.current?.focus();
  }, [refusal, done]);

  const final = refusal !== null && decisionNext(refusal) === "reject";

  async function run(decision: Decision) {
    setBusy(true);
    setRefusal(null);
    const outcome = await calls.decide(eventId, decision, seen);
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
    if (decisionNext(outcome.refusal.code) === "reload") router.refresh();
  }

  function ask(decision: Decision) {
    if (busy || (decision === "publish" && final)) return;
    setChoice(decision);
    openConfirm(dialog.current);
  }

  if (done) {
    return (
      <Alert tone="ok" ref={notice}>
        <p data-decision={done}>{done === "publish" ? t("decision.published") : t("decision.rejected")}</p>
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
          <p data-refusal={refusal}>{tf(`refusal.${refusal}`, { org: "" })}</p>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button
          id="decision-publish"
          variant={final ? "secondary" : "primary"}
          busy={busy}
          aria-disabled={busy || final || undefined}
          onClick={() => ask("publish")}
        >
          {t("decision.publish")}
        </Button>
        <Button id="decision-reject" variant={final ? "primary" : "secondary"} busy={busy} onClick={() => ask("reject")}>
          {t("decision.reject")}
        </Button>
      </div>
      <ConfirmDialog
        ref={dialog}
        title={choice === "publish" ? t("decision.publishTitle") : t("decision.rejectTitle")}
        confirmLabel={choice === "publish" ? t("decision.publish") : t("decision.reject")}
        busyLabel={choice === "publish" ? t("decision.publishing") : t("decision.rejecting")}
        busy={busy}
        tone={choice === "publish" ? "primary" : "danger"}
        cancelLabel={t("decision.cancel")}
        onConfirm={() => void run(choice)}
      >
        <p>{choice === "publish" ? t("decision.publishBody") : t("decision.rejectBody")}</p>
      </ConfirmDialog>
    </div>
  );
}
