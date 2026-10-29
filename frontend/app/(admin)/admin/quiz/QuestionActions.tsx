"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { TextAreaField } from "@/components/ui/TextAreaField";

import { StepUp } from "../research/StepUp";
import { adminQuizCalls, type AdminQuizCalls } from "./calls";
import { MAX_REASON, questionRefusal, type RefusalCode } from "./quiz";

export interface QuestionActionsProps {
  questionId: string;
  /** The question's position (1 to 5), which names it on the buttons and in the dialog. */
  number: number;
  status: "live" | "pulled";
  calls?: AdminQuizCalls;
}

/**
 * Pull (with a reason) or Restore one question (REQ-DEV-01; POST /api/admin/quiz/questions/{id}/pull | restore): each
 * asks once in a dialog that says what follows (every play of the set is scored again). A stale second factor asks for
 * a fresh code in place, then repeats the step. Done: one sentence with how many plays were scored again, and the page
 * is fetched again.
 */
export function QuestionActions({ questionId, number, status, calls: given }: QuestionActionsProps) {
  const t = useStrings("adminQuiz");
  const router = useRouter();
  const calls = useRef(given ?? adminQuizCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const said = useRef<HTMLDivElement>(null);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [refusal, setRefusal] = useState<RefusalCode | null>(null);
  const [done, setDone] = useState<number | null>(null);
  const action = status === "live" ? "pull" : "restore";
  const fieldId = `pull-reason-${number}`;
  const buttonId = `question-action-${number}`;

  useEffect(() => {
    if (refusal || done !== null) said.current?.focus();
  }, [refusal, done]);

  async function run() {
    if (busy) return;
    if (action === "pull" && !reason.trim()) {
      setMissing(true);
      document.getElementById(fieldId)?.focus();
      return;
    }
    setBusy(true);
    setRefusal(null);
    const outcome = action === "pull" ? await calls.pull(questionId, reason) : await calls.restore(questionId);
    setBusy(false);
    dialog.current?.close();
    if (outcome.ok) {
      setStepUp(false);
      setDone(outcome.data.rescored);
      router.refresh();
    } else if (outcome.refusal.kind === "stepUp") {
      setStepUp(true);
    } else {
      setStepUp(false);
      setRefusal(questionRefusal(outcome.refusal.code));
      router.refresh();
    }
  }

  if (done !== null) {
    return (
      <Alert tone="ok" ref={said}>
        <p data-question-done={action}>{t(`${action}.done`, { count: done })}</p>
      </Alert>
    );
  }

  if (stepUp) {
    return (
      <StepUp
        onConfirmed={run}
        onCancel={() => {
          setStepUp(false);
          requestAnimationFrame(() => document.getElementById(buttonId)?.focus());
        }}
      />
    );
  }

  return (
    <div className="flex flex-col items-start gap-3">
      {refusal ? (
        <Alert ref={said} className="w-full">
          <p data-refusal={refusal}>{t(`refusal.${refusal}`)}</p>
        </Alert>
      ) : null}
      <Button
        id={buttonId}
        variant={action === "pull" ? "danger" : "secondary"}
        aria-label={t(`${action}.openNamed`, { number })}
        onClick={() => {
          setMissing(false);
          openConfirm(dialog.current);
        }}
        data-question-action={action}
      >
        {t(`${action}.open`)}
      </Button>
      <ConfirmDialog
        ref={dialog}
        title={t(`${action}.title`, { number })}
        confirmLabel={t(`${action}.confirm`)}
        busyLabel={t(`${action}.busy`)}
        busy={busy}
        tone={action === "pull" ? "danger" : "primary"}
        cancelLabel={t("decision.cancel")}
        onConfirm={() => void run()}
      >
        <p>{t(`${action}.body`)}</p>
        {action === "pull" ? (
          <div className="mt-4">
            <TextAreaField
              id={fieldId}
              label={t("pull.reasonLabel")}
              hint={t("pull.reasonHint", { max: MAX_REASON })}
              rows={2}
              maxLength={MAX_REASON}
              value={reason}
              onChange={(event) => {
                setReason(event.currentTarget.value);
                setMissing(false);
              }}
              error={missing ? t("pull.reasonMissing") : undefined}
            />
          </div>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
