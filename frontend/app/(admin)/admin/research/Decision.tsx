"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";

import { decide, type Decision as Choice } from "./calls";
import { refusalKey, type Refusal } from "./research";
import { StepUp } from "./StepUp";

type Phase =
  | { kind: "idle" }
  | { kind: "confirmReject" }
  | { kind: "busy"; choice: Choice }
  | { kind: "stepUp"; choice: Choice }
  | { kind: "done"; choice: Choice };

export interface DecisionProps {
  problemId: string;
  /** The card names an organisation: the D-45 checklist must be ticked before it can be approved. */
  needsChecklist: boolean;
  /** Where the published card is read (the signed-in problem page). */
  publicHref: string;
  researchHref: string;
  decideImpl?: typeof decide;
}

/**
 * The staff admin's decision on one research card (REQ-RES-01; POST …/candidates/{problem_id}/decision). "Approve
 * and publish" is the screen's one primary action: the API runs the publish checks again and publishes through
 * app_moderate_problem. "Reject" asks once more, since a rejected card can never be published. A card naming an
 * organisation needs the checklist ticked first (D-45). Every refusal is a fixed sentence; a stale second factor
 * asks for a fresh code, then repeats the decision.
 */
export function Decision({ problemId, needsChecklist, publicHref, researchHref, decideImpl = decide }: DecisionProps) {
  const t = useStrings("adminResearch");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [refusal, setRefusal] = useState<Exclude<Refusal, { kind: "stepUp" }> | null>(null);
  const [checked, setChecked] = useState(false);
  const [checklistError, setChecklistError] = useState(false);
  const noticeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (refusal || phase.kind === "done") noticeRef.current?.focus();
  }, [refusal, phase.kind]);

  async function run(choice: Choice) {
    setRefusal(null);
    setPhase({ kind: "busy", choice });
    const outcome = await decideImpl(problemId, choice, needsChecklist && checked);
    if (outcome.ok) {
      setPhase({ kind: "done", choice });
    } else if (outcome.refusal.kind === "stepUp") {
      setPhase({ kind: "stepUp", choice });
    } else {
      setRefusal(outcome.refusal);
      setPhase({ kind: "idle" });
    }
  }

  function approve() {
    if (phase.kind === "busy") return;
    if (needsChecklist && !checked) {
      setChecklistError(true);
      document.getElementById("checklist-confirm")?.focus();
      return;
    }
    void run("approve");
  }

  if (phase.kind === "done") {
    const published = phase.choice === "approve";
    return (
      <div className="flex flex-col items-start gap-3">
        <Alert tone="ok" ref={noticeRef} className="w-full">
          <p data-decision={phase.choice}>{published ? t("review.published") : t("review.rejected")}</p>
        </Alert>
        {published ? (
          <Link href={publicHref} className={standaloneLinkClass}>
            {t("review.openPublic")}
          </Link>
        ) : null}
        <Link href={researchHref} className={standaloneLinkClass}>
          {t("review.backToResearch")}
        </Link>
      </div>
    );
  }

  if (phase.kind === "stepUp") {
    const choice = phase.choice;
    return <StepUp onConfirmed={() => run(choice)} onCancel={() => setPhase({ kind: "idle" })} />;
  }

  const busy = phase.kind === "busy";
  return (
    <div className="flex flex-col gap-5">
      {refusal ? (
        <Alert ref={noticeRef}>
          <p data-refusal={refusalKey(refusal)}>{t(refusalKey(refusal))}</p>
        </Alert>
      ) : null}
      {needsChecklist ? (
        <Checkbox
          id="checklist-confirm"
          label={t("review.checklistConfirm")}
          checked={checked}
          error={checklistError && !checked ? t("review.checklistRequired") : undefined}
          onChange={(event) => {
            setChecked(event.target.checked);
            setChecklistError(false);
          }}
        />
      ) : null}
      {phase.kind === "confirmReject" ? (
        <div className="flex flex-col items-start gap-3 border-l-2 border-error pl-4">
          <p className="max-w-[60ch] text-ink">{t("review.rejectConfirm")}</p>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Button variant="secondary" onClick={() => void run("reject")}>
              {t("review.rejectYes")}
            </Button>
            <Button variant="link" onClick={() => setPhase({ kind: "idle" })}>
              {t("review.cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button variant="primary" busy={busy} onClick={approve}>
            {busy && phase.choice === "approve" ? t("review.approving") : t("review.approve")}
          </Button>
          <Button variant="secondary" busy={busy} onClick={() => setPhase({ kind: "confirmReject" })}>
            {busy && phase.choice === "reject" ? t("review.rejecting") : t("review.reject")}
          </Button>
        </div>
      )}
    </div>
  );
}
