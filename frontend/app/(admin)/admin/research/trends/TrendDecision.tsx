"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { StepUp } from "../StepUp";
import { trendCalls, type TrendCalls, type TrendDecision as Choice } from "./calls";
import type { TrendRefusalCode } from "./trends";

/**
 * The staff admin's decision on a trend card (REQ-DEV-02; D-60): "Publish" is the screen's one primary action and
 * "Reject" the other, each confirmed in a dialog that says what follows. The API repeats the named-organisation rule
 * on publish: a card naming an organisation no source names (409 unsourced_name) can only be rejected, so Reject
 * becomes the primary action. A stale second factor asks for a fresh code, then repeats the decision.
 */
export function TrendDecision({ cardId, calls: given }: { cardId: string; calls?: TrendCalls }) {
  const t = useStrings("adminResearch");
  const router = useRouter();
  const calls = useRef(given ?? trendCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const notice = useRef<HTMLDivElement>(null);
  const [choice, setChoice] = useState<Choice>("publish");
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [refusal, setRefusal] = useState<TrendRefusalCode | null>(null);
  const [done, setDone] = useState<Choice | null>(null);

  useEffect(() => {
    if (refusal || done) notice.current?.focus();
  }, [refusal, done]);

  const final = refusal === "unsourced_name";

  async function run(decision: Choice) {
    setBusy(true);
    setRefusal(null);
    const outcome = await calls.decide(cardId, decision);
    setBusy(false);
    dialog.current?.close();
    if (outcome.ok) {
      setStepUp(false);
      setDone(decision);
      return;
    }
    if (outcome.refusal.kind === "stepUp") return setStepUp(true);
    setStepUp(false);
    setRefusal(outcome.refusal.code);
    if (outcome.refusal.code === "already_decided" || outcome.refusal.code === "not_found") router.refresh();
  }

  function ask(decision: Choice) {
    if (busy || (decision === "publish" && final)) return;
    setChoice(decision);
    openConfirm(dialog.current);
  }

  if (done) {
    return (
      <Alert tone="ok" ref={notice}>
        <p data-decision={done}>{done === "publish" ? t("trends.review.published") : t("trends.review.rejected")}</p>
      </Alert>
    );
  }
  if (stepUp) {
    return (
      <StepUp
        onConfirmed={() => run(choice)}
        onCancel={() => {
          setStepUp(false);
          requestAnimationFrame(() => document.getElementById(`trend-${choice}`)?.focus());
        }}
      />
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {refusal ? (
        <Alert ref={notice}>
          <p data-refusal={refusal}>{t(`trends.refusal.${refusal}`)}</p>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button id="trend-publish" variant={final ? "secondary" : "primary"} busy={busy} aria-disabled={busy || final || undefined} onClick={() => ask("publish")}>
          {t("trends.review.publish")}
        </Button>
        <Button id="trend-reject" variant={final ? "primary" : "secondary"} busy={busy} onClick={() => ask("reject")}>
          {t("trends.review.reject")}
        </Button>
      </div>
      <ConfirmDialog
        ref={dialog}
        title={choice === "publish" ? t("trends.review.publishTitle") : t("trends.review.rejectTitle")}
        confirmLabel={choice === "publish" ? t("trends.review.publish") : t("trends.review.reject")}
        busyLabel={choice === "publish" ? t("trends.review.publishing") : t("trends.review.rejecting")}
        busy={busy}
        tone={choice === "publish" ? "primary" : "danger"}
        cancelLabel={t("trends.review.cancel")}
        onConfirm={() => void run(choice)}
      >
        <p>{choice === "publish" ? t("trends.review.publishBody") : t("trends.review.rejectBody")}</p>
      </ConfirmDialog>
    </div>
  );
}
