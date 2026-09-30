"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";

import { decide, type Decision as Choice } from "./calls";
import { refusalKey, refusalNext, type Refusal } from "./research";
import { StepUp } from "./StepUp";

type Phase =
  | { kind: "idle" }
  | { kind: "confirmReject" }
  | { kind: "busy"; choice: Choice }
  | { kind: "stepUp"; choice: Choice }
  | { kind: "done"; choice: Choice };

export interface DecisionProps {
  problemId: string;
  /** The card lists organisations it names: the D-45 checklist is shown on the page and must be ticked. */
  needsChecklist: boolean;
  /** The API's checklist text (D-45 placeholder), shown here when the API asks for it on a card that lists none. */
  checklist: readonly string[];
  /** Where the published card is read (the signed-in problem page). */
  publicHref: string;
  researchHref: string;
  decideImpl?: typeof decide;
}

const REJECT_ID = "decision-reject";
const CONFIRM_ID = "decision-reject-confirm";
const QUESTION_ID = "decision-reject-question";
const CHECKBOX_ID = "checklist-confirm";

function focusSoon(id: string) {
  requestAnimationFrame(() => document.getElementById(id)?.focus());
}

/**
 * The staff admin's decision on one research card (REQ-RES-01; POST …/candidates/{problem_id}/decision). "Approve
 * and publish" is the screen's one primary action: the API runs the publish checks again and publishes through
 * app_moderate_problem. "Reject" asks once more (the question takes focus; Cancel returns it), since a rejected card
 * can never be published. A card naming an organisation needs the checklist ticked first (D-45); when the API finds a
 * name the card does not list (409 checklist_required), the checklist appears here. Every refusal is a fixed
 * sentence; after a failed publish check Reject becomes the primary action, and a card already decided leaves only
 * the way back. A stale second factor asks for a fresh code, then repeats the decision.
 */
export function Decision({
  problemId,
  needsChecklist,
  checklist,
  publicHref,
  researchHref,
  decideImpl = decide,
}: DecisionProps) {
  const t = useStrings("adminResearch");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [refusal, setRefusal] = useState<Exclude<Refusal, { kind: "stepUp" }> | null>(null);
  const [askedForChecklist, setAskedForChecklist] = useState(false);
  const [checked, setChecked] = useState(false);
  const [checklistError, setChecklistError] = useState(false);
  const noticeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (refusal || phase.kind === "done") noticeRef.current?.focus();
  }, [refusal, phase.kind]);

  const showChecklist = needsChecklist || askedForChecklist;
  const next = refusal ? refusalNext(refusal) : null;

  async function run(choice: Choice) {
    setRefusal(null);
    setPhase({ kind: "busy", choice });
    const outcome = await decideImpl(problemId, choice, showChecklist && checked);
    if (outcome.ok) {
      setPhase({ kind: "done", choice });
    } else if (outcome.refusal.kind === "stepUp") {
      setPhase({ kind: "stepUp", choice });
    } else {
      if (outcome.refusal.kind === "refusal" && outcome.refusal.code === "checklist_required") {
        setAskedForChecklist(true);
      }
      setRefusal(outcome.refusal);
      setPhase({ kind: "idle" });
    }
  }

  function approve() {
    if (phase.kind === "busy" || next) return;
    if (showChecklist && !checked) {
      setChecklistError(true);
      document.getElementById(CHECKBOX_ID)?.focus();
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
    return (
      <StepUp
        onConfirmed={() => run(choice)}
        onCancel={() => {
          setPhase({ kind: "idle" });
          focusSoon(choice === "approve" ? "decision-approve" : REJECT_ID);
        }}
      />
    );
  }

  const notice = refusal ? (
    <Alert ref={noticeRef}>
      <p data-refusal={refusalKey(refusal)}>{t(refusalKey(refusal))}</p>
    </Alert>
  ) : null;

  if (next === "back") {
    return (
      <div className="flex flex-col items-start gap-4">
        {notice}
        <Link href={researchHref} data-primary="" className={buttonClass("primary", "no-underline")}>
          {t("review.backToResearch")}
        </Link>
      </div>
    );
  }

  const busy = phase.kind === "busy";
  const final = next === "reject";
  return (
    <div className="flex flex-col gap-5">
      {notice}
      {askedForChecklist && !needsChecklist && checklist.length > 0 ? (
        <ul className="flex max-w-[65ch] list-disc flex-col gap-2 pl-5 text-ink" data-checklist="">
          {checklist.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {showChecklist && !final ? (
        <Checkbox
          id={CHECKBOX_ID}
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
        <div
          id={CONFIRM_ID}
          role="group"
          tabIndex={-1}
          aria-labelledby={QUESTION_ID}
          data-confirm="reject"
          className="flex flex-col items-start gap-3 border-l-2 border-error pl-4 focus:outline-none"
        >
          <p id={QUESTION_ID} className="max-w-[60ch] text-ink">
            {t("review.rejectConfirm")}
          </p>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Button variant={final ? "primary" : "secondary"} onClick={() => void run("reject")}>
              {t("review.rejectYes")}
            </Button>
            <Button
              variant="link"
              onClick={() => {
                setPhase({ kind: "idle" });
                focusSoon(REJECT_ID);
              }}
            >
              {t("review.cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button
            id="decision-approve"
            variant={final ? "secondary" : "primary"}
            busy={busy}
            aria-disabled={busy || final || undefined}
            onClick={approve}
          >
            {busy && phase.choice === "approve" ? t("review.approving") : t("review.approve")}
          </Button>
          <Button
            id={REJECT_ID}
            variant={final ? "primary" : "secondary"}
            busy={busy}
            onClick={() => {
              setPhase({ kind: "confirmReject" });
              focusSoon(CONFIRM_ID);
            }}
          >
            {busy && phase.choice === "reject" ? t("review.rejecting") : t("review.reject")}
          </Button>
        </div>
      )}
    </div>
  );
}
