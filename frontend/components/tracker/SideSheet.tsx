"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button, buttonClass } from "@/components/ui/Button";
import { SheetHandle, sheetClass } from "@/components/ui/ConfirmDialog";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import { formatDate, nairobiToday, type SheetCommand, type SheetInput, type SideLimits } from "./model";
import { addDays, HOLD_MAX_DAYS, longDate, QUESTION_MAX_CHARS, REASON_MAX_CHARS } from "./sheet";

// The side states' sheets (REQ-ENG-10 part; docs/spec/06 6.9 side branches): a question, its answer, a hold, an early
// resume, and the organisation's withdrawal of its question. Each is a native modal <dialog> drawn as the confirmation
// dialogs are (a bottom sheet on phones, D-52), with a form inside: the text the other party reads, and a hold's
// date. The sheet checks only that the text is there; the API decides the rest (a 422 comes back as a refusal inside
// the sheet). Loaded when one opens (Actions.tsx), so the tracker's first load carries none of it.

export interface SideSheetProps {
  command: SheetCommand;
  busy: boolean;
  /** The refusal of the last attempt, shown above the buttons. */
  problem?: ReactNode;
  /** The other party's name. */
  counterpart: string;
  /** answer_info: the organisation's question and the day it was asked ("2 Oct 2026"). */
  question?: { body: string; date: string } | null;
  /** resume: the day the hold was due to end ("12 Oct 2026"). */
  resumeOn?: string | null;
  locale?: string;
  /** Today in Nairobi on the app's clock ("2026-10-02"), for the hold's date range. */
  today?: string;
  /** What the policy's caps leave this stage (the API's `side_limits`); each figure shown only when sent. */
  limits?: SideLimits | null;
  onSubmit: (input: SheetInput) => void;
  /** The sheet closed without sending (Cancel or Escape). */
  onClose: () => void;
}

const SUBMIT = {
  request_info: "sheet.requestInfo.submit",
  answer_info: "sheet.answerInfo.submit",
  pause: "sheet.pause.submit",
  resume: "sheet.resume.submit",
  cancel_request: "sheet.cancelRequest.submit",
} as const satisfies Record<SheetCommand, string>;

export function SideSheet(props: SideSheetProps) {
  const t = useStrings("trackerActions");
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const id = useId();
  const locale = props.locale ?? "en";
  const today = props.today ?? nairobiToday();
  const [text, setText] = useState("");
  const [resumeAt, setResumeAt] = useState("");
  const [errors, setErrors] = useState<{ text?: string; date?: string }>({});
  const ids = { text: `${id}-text`, date: `${id}-date` };

  // Opens as a modal once mounted; focus goes to the first field (to Cancel when there is none, as a confirmation).
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    const first = dialog.querySelector<HTMLElement>("[data-sheet-first]") ?? dialog.querySelector<HTMLElement>("[data-dialog-cancel]");
    first?.focus();
  }, []);

  const withText = props.command !== "cancel_request";
  // A hold's date, as the API checks it: after today, at most 60 days ahead and within the days on hold the
  // engagement has left (side_limits.hold_days_left, when sent).
  const earliest = addDays(today, 1);
  const latest = addDays(today, Math.max(1, Math.min(HOLD_MAX_DAYS, props.limits?.hold_days_left ?? HOLD_MAX_DAYS)));
  const outOfRange = (day: string) => !/^\d{4}-\d{2}-\d{2}$/.test(day) || day < earliest || day > latest;
  const rangeError = t("sheet.pause.dateRange", { date: formatDate(earliest, locale), value: formatDate(latest, locale) });
  const left = (figure: number | null | undefined, key: "sheet.questionsLeft" | "sheet.holdsLeft" | "sheet.holdDaysLeft") =>
    figure == null ? null : (
      <li key={key} data-left={key.slice(6)}>
        {t(key, { count: figure })}
      </li>
    );
  const lefts =
    props.command === "request_info"
      ? [left(props.limits?.questions_left, "sheet.questionsLeft")]
      : props.command === "pause"
        ? [left(props.limits?.holds_left, "sheet.holdsLeft"), left(props.limits?.hold_days_left, "sheet.holdDaysLeft")]
        : [];
  const leftList = lefts.some(Boolean) ? <ul className="flex flex-col gap-1 text-sm text-ink-soft">{lefts}</ul> : null;
  const multiLine = props.command === "request_info" || props.command === "answer_info";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (props.busy) return;
    const value = text.trim();
    const next = {
      text: withText && !value ? t("form.required") : undefined,
      date: props.command !== "pause" ? undefined : !resumeAt ? t("form.date") : outOfRange(resumeAt) ? rangeError : undefined,
    };
    setErrors(next);
    if (next.text || next.date) {
      document.getElementById(next.text ? ids.text : ids.date)?.focus();
      return;
    }
    switch (props.command) {
      case "request_info":
        return props.onSubmit({ question: value });
      case "answer_info":
        return props.onSubmit({ answer: value });
      case "pause":
        return props.onSubmit({ reason: value, resume_at: resumeAt });
      case "resume":
        return props.onSubmit({ reason: value });
      case "cancel_request":
        return props.onSubmit({});
    }
  }

  const count = new Intl.NumberFormat(`${locale}-KE`);
  const textField = multiLine ? (
    <TextAreaField
      id={ids.text}
      data-sheet-first=""
      label={t(props.command === "request_info" ? "sheet.requestInfo.label" : "sheet.answerInfo.label")}
      hint={t("sheet.noContact")}
      meter={t("sheet.count", { count: count.format(text.length), max: count.format(QUESTION_MAX_CHARS) })}
      maxLength={QUESTION_MAX_CHARS}
      rows={5}
      value={text}
      error={errors.text}
      onChange={(e) => {
        setText(e.target.value);
        setErrors((current) => ({ ...current, text: undefined }));
      }}
    />
  ) : withText ? (
    <TextField
      id={ids.text}
      data-sheet-first=""
      label={t(props.command === "pause" ? "sheet.pause.reason" : "sheet.resume.reason")}
      hint={t(props.command === "pause" ? "sheet.pause.reasonHint" : "sheet.resume.reasonHint")}
      maxLength={REASON_MAX_CHARS}
      autoComplete="off"
      value={text}
      error={errors.text}
      onChange={(e) => {
        setText(e.target.value);
        setErrors((current) => ({ ...current, text: undefined }));
      }}
    />
  ) : null;

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        if (props.busy) event.preventDefault();
      }}
      onClose={props.onClose}
      data-sheet=""
      data-side-sheet={props.command}
      className={sheetClass("lg")}
    >
      <SheetHandle />
      <h2 id={titleId} className="text-lg text-ink">
        {t(`command.${props.command}`)}
      </h2>
      <form noValidate onSubmit={submit} data-command-form={props.command} className="mt-3 flex flex-col gap-5">
        {props.command === "request_info" ? (
          <div className="flex flex-col gap-2">
            <p className="max-w-[60ch] text-ink">{t("sheet.requestInfo.lead", { name: props.counterpart })}</p>
            <p className="max-w-[60ch] text-sm text-ink-soft">{t("sheet.requestInfo.limit")}</p>
            {leftList}
          </div>
        ) : null}

        {props.command === "answer_info" ? (
          <>
            {props.question ? (
              <figure className="rounded-control border border-line bg-field p-4">
                <figcaption className="text-sm text-ink-soft">
                  {t("sheet.answerInfo.asked", { name: props.counterpart, date: props.question.date })}
                </figcaption>
                <blockquote data-question="" className="mt-1 whitespace-pre-line text-ink [overflow-wrap:anywhere]">
                  {props.question.body}
                </blockquote>
              </figure>
            ) : null}
            <p className="max-w-[60ch] text-ink">{t("sheet.answerInfo.lead")}</p>
          </>
        ) : null}

        {props.command === "pause" ? (
          <div className="flex flex-col gap-2">
            <p className="max-w-[60ch] text-ink">{t("sheet.pause.lead")}</p>
            {leftList}
          </div>
        ) : null}
        {props.command === "resume" ? (
          <p className="max-w-[60ch] text-ink">
            {props.resumeOn ? t("sheet.resume.lead", { date: props.resumeOn }) : t("sheet.resume.leadNoDate")}
          </p>
        ) : null}
        {props.command === "cancel_request" ? (
          <p className="max-w-[60ch] text-ink">{t("sheet.cancelRequest.body", { name: props.counterpart })}</p>
        ) : null}

        {textField}

        {props.command === "pause" ? (
          <div className="flex flex-col gap-2">
            <TextField
              id={ids.date}
              type="date"
              label={t("sheet.pause.date")}
              hint={t("sheet.pause.dateHint", { date: formatDate(latest, locale) })}
              min={earliest}
              max={latest}
              value={resumeAt}
              error={errors.date}
              onChange={(e) => {
                setResumeAt(e.target.value);
                setErrors((current) => ({ ...current, date: undefined }));
              }}
              className="max-w-[14rem]"
            />
            {/* The chosen date in words, with its weekday, said politely as it changes. */}
            <p aria-live="polite" data-resumes="" className="text-sm text-ink">
              {resumeAt ? t("sheet.pause.resumes", { date: longDate(resumeAt, locale) }) : ""}
            </p>
          </div>
        ) : null}

        {props.problem}

        {/* Cancel first, on top on phones and on the left from 640 px (the confirmations' order); the send button is
            styled, not marked, as primary: the screen's data-primary stays on the page's own action. */}
        <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" busy={props.busy} onClick={() => ref.current?.close()} data-dialog-cancel="">
            {t("cancel")}
          </Button>
          <button type="submit" aria-disabled={props.busy || undefined} data-dialog-confirm="" className={buttonClass("primary")}>
            {props.busy ? t("busy") : t(SUBMIT[props.command])}
          </button>
        </div>
      </form>
    </dialog>
  );
}
