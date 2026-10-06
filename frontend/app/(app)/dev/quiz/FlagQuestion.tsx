"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass } from "@/components/ui/Button";
import { SheetHandle, sheetClass } from "@/components/ui/ConfirmDialog";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { TextAreaField } from "@/components/ui/TextAreaField";

import { quizCalls, type QuizCalls } from "./calls";
import { FLAG_REASONS, flagEndsSheet, MAX_NOTE, type FlagOutcome, type FlagReason } from "./quiz";

export interface FlagQuestionProps {
  questionId: string;
  /** The question's position (1 to 5), which names it on the button and the sheet. */
  number: number;
  calls?: QuizCalls;
}

/**
 * "Flag" under a finished question (REQ-DEV-01): a small sheet (a bottom sheet on phones, a dialog from 640 px) with
 * the four reasons, an optional note for staff and one action, "Send". Sent, already flagged or already withdrawn:
 * the sheet closes and one sentence takes the button's place, with focus. The daily limit and a failure are said in
 * the sheet, which stays open.
 */
export function FlagQuestion({ questionId, number, calls: given }: FlagQuestionProps) {
  const t = useStrings("quizPlay");
  const calls = useRef(given ?? quizCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const said = useRef<HTMLParagraphElement>(null);
  const titleId = useId();
  const [reason, setReason] = useState<FlagReason | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<FlagOutcome | null>(null);
  const [ended, setEnded] = useState<FlagOutcome | null>(null);
  const base = `flag-${number}`;

  useEffect(() => {
    if (ended) said.current?.focus();
  }, [ended]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!reason) {
      setMissing(true);
      document.getElementById(`${base}-reason-${FLAG_REASONS[0]}`)?.focus();
      return;
    }
    setBusy(true);
    setProblem(null);
    const outcome = await calls.flag(questionId, reason, String(new FormData(event.currentTarget).get("note") ?? ""));
    setBusy(false);
    if (flagEndsSheet(outcome)) {
      setEnded(outcome);
      dialog.current?.close();
    } else {
      setProblem(outcome);
    }
  }

  if (ended) {
    return (
      <p ref={said} tabIndex={-1} role="status" data-flag-outcome={ended} className="text-sm font-semibold text-ink focus:outline-none">
        {t(`flag.outcome.${ended}`)}
      </p>
    );
  }

  return (
    <>
      <button
        type="button"
        aria-label={t("flag.openNamed", { number })}
        aria-haspopup="dialog"
        onClick={() => {
          setProblem(null);
          dialog.current?.showModal();
        }}
        className="btn btn-link self-start"
        data-flag-open=""
      >
        {t("flag.open")}
      </button>
      <dialog ref={dialog} aria-labelledby={titleId} data-sheet="" className={sheetClass()}>
        <SheetHandle />
        <h2 id={titleId} className="text-lg text-ink">
          {t("flag.title", { number })}
        </h2>
        <p className="mt-1 text-sm text-ink-soft">{t("flag.lead")}</p>
        <form noValidate onSubmit={send} className="mt-5 flex flex-col gap-5">
          <RadioGroup
            id={`${base}-reason`}
            name={`${base}-reason`}
            legend={t("flag.legend")}
            options={FLAG_REASONS.map((value) => ({ value, label: t(`flag.reason.${value}`) }))}
            value={reason}
            onChange={(value) => {
              setReason(value);
              setMissing(false);
            }}
            error={missing ? t("flag.pickReason") : undefined}
          />
          <TextAreaField
            id={`${base}-note`}
            name="note"
            rows={2}
            maxLength={MAX_NOTE}
            label={t("flag.noteLabel")}
            hint={t("flag.noteHint", { max: MAX_NOTE })}
          />
          {problem ? (
            <Alert>
              <p data-flag-problem={problem}>{t(`flag.outcome.${problem}`)}</p>
            </Alert>
          ) : null}
          <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
            <Button busy={busy} onClick={() => dialog.current?.close()}>
              {t("flag.cancel")}
            </Button>
            <button type="submit" aria-disabled={busy || undefined} className={buttonClass("primary")}>
              {busy ? t("flag.sending") : t("flag.send")}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
