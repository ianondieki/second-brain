"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { SheetHandle, sheetClass } from "@/components/ui/ConfirmDialog";
import { FieldError } from "@/components/ui/Field";
import { TextField } from "@/components/ui/TextField";
import { formatCalendarDate, formatDay } from "@/lib/format";

import { declare as declareCall, type Declaration, type DeclarationOutcome, type DeclarationRefusal } from "./calls";
import { isOneLine } from "@/lib/one-line";

import { focusLineWhenRefreshed } from "./focus-line";
import { asSha256, HASH_MAX_BYTES, sha256Hex } from "./hash";

// The prior-knowledge declaration (REQ-PROV-06; docs/spec/06 6.4 pt 5), on the organisation's tracker while it may
// declare: a native modal <dialog> drawn as the tracker's other sheets are (a bottom sheet on phones, D-52). The
// evidence is a file hashed here with Web Crypto (SHA-256; the file is read in memory and never sent) or a SHA-256
// pasted from elsewhere; with it, the evidence's title (kept for good: "a short title, no names") and its date, on
// or before the day the organisation first viewed the full proposal. The API decides; its refusals are said by
// code, on the field they concern. After it is recorded, the sheet shows the receipt. Loaded when it opens
// (components/tracker/lazy.tsx), so the tracker's first load carries none of it.

export interface DeclarationSheetProps {
  orgId: string;
  engagementId: string;
  /** The window's last day ("2026-10-16", the API's `window_closes_on`). */
  closesOn: string;
  /** The Nairobi day of the organisation's first full-proposal view ("2026-10-02"): the evidence's latest date. */
  firstViewOn: string;
  locale?: string;
  /** The sheet closed; `changed` once a declaration was recorded (the tracker behind it refreshes). */
  onClose: (changed: boolean) => void;
  declareImpl?: typeof declareCall;
  hashImpl?: (file: Blob) => Promise<string>;
}

/** The evidence's title: one line, at most 200 characters (engagements/models.py EVIDENCE_TITLE_MAX_CHARS). */
export const TITLE_MAX = 200;

type Source = "file" | "paste";
type Errors = { hash?: string; title?: string; date?: string };
type FileState = { kind: "none" } | { kind: "hashing"; name: string } | { kind: "done"; name: string; hash: string };

/** Refusals after which the tracker has changed for good (the action is gone once it refreshes). */
const FINAL: ReadonlySet<DeclarationRefusal> = new Set(["windowClosed", "alreadyDeclared", "ended"]);

const FIELD_OF: Partial<Record<DeclarationRefusal, keyof Errors>> = {
  invalidTitle: "title",
  future: "date",
  afterView: "date",
  invalidHash: "hash",
};

export function DeclarationSheet(props: DeclarationSheetProps) {
  const t = useStrings("declarationSheet");
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const id = useId();
  const locale = props.locale ?? "en";
  const declare = props.declareImpl ?? declareCall;
  const hashOf = props.hashImpl ?? sha256Hex;
  const [source, setSource] = useState<Source>("file");
  const [file, setFile] = useState<FileState>({ kind: "none" });
  const [pasted, setPasted] = useState("");
  const [title, setTitle] = useState("");
  const [dated, setDated] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<{ text: string; n: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [recorded, setRecorded] = useState<Declaration | null>(null);
  // Recorded, or refused for good: closing refreshes the tracker behind (the action goes).
  const [changed, setChanged] = useState(false);
  // Each file chosen gets a number: a fingerprint that comes back after a later choice is dropped.
  const chosenRef = useRef(0);
  const receipt = useRef<HTMLHeadingElement>(null);
  const problemRef = useRef<HTMLDivElement>(null);
  const ids = { hash: `${id}-hash`, file: `${id}-file`, title: `${id}-title`, date: `${id}-date` };
  const firstView = formatCalendarDate(locale, props.firstViewOn);
  const closes = formatCalendarDate(locale, props.closesOn);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    dialog?.querySelector<HTMLElement>("[data-sheet-first]")?.focus();
  }, []);

  useEffect(() => {
    if (recorded) receipt.current?.focus();
  }, [recorded]);

  useEffect(() => {
    if (problem) problemRef.current?.focus();
  }, [problem]);

  async function choose(chosen: File | undefined) {
    setErrors((now) => ({ ...now, hash: undefined }));
    if (!chosen) {
      chosenRef.current++;
      setFile({ kind: "none" });
      return;
    }
    if (chosen.size > HASH_MAX_BYTES) {
      chosenRef.current++;
      setFile({ kind: "none" });
      setErrors((now) => ({ ...now, hash: t("tooLarge") }));
      return;
    }
    const tag = ++chosenRef.current;
    setFile({ kind: "hashing", name: chosen.name });
    try {
      const hash = await hashOf(chosen);
      if (tag === chosenRef.current) setFile({ kind: "done", name: chosen.name, hash });
    } catch {
      if (tag !== chosenRef.current) return;
      setFile({ kind: "none" });
      setErrors((now) => ({ ...now, hash: t("hashFailed") }));
    }
  }

  const hash = source === "file" ? (file.kind === "done" ? file.hash : null) : asSha256(pasted);
  // Only the file way waits for its fingerprint; a pasted hash sends at once.
  const hashing = source === "file" && file.kind === "hashing";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || hashing) return;
    const value = title.trim();
    const next: Errors = {
      hash: hash ? undefined : source === "file" ? t("needFile") : t("invalidHash"),
      title: !value ? t("needTitle") : isOneLine(value) ? undefined : t("refusal.invalidTitle"),
      date: !dated ? t("needDate") : dated > props.firstViewOn ? t("dateAfter", { date: firstView }) : undefined,
    };
    setErrors(next);
    setProblem(null);
    const first = (["hash", "title", "date"] as const).find((field) => next[field]);
    if (first) {
      document.getElementById(first === "hash" ? (source === "file" ? ids.file : ids.hash) : ids[first])?.focus();
      return;
    }
    setBusy(true);
    const outcome: DeclarationOutcome = await declare(props.orgId, props.engagementId, {
      evidence_sha256_hex: hash!,
      evidence_title: value,
      evidence_dated_on: dated,
    });
    setBusy(false);
    if (outcome.ok) {
      setChanged(true);
      setRecorded(outcome.declaration);
      return;
    }
    if (FINAL.has(outcome.refusal)) setChanged(true);
    const field = FIELD_OF[outcome.refusal];
    if (field) {
      const text =
        outcome.refusal === "afterView" ? t("refusal.afterView", { date: firstView }) : t(`refusal.${outcome.refusal}`);
      setErrors({ [field]: text });
      document.getElementById(field === "hash" ? (source === "file" ? ids.file : ids.hash) : ids[field])?.focus();
      return;
    }
    const text =
      outcome.refusal === "windowClosed"
        ? outcome.closedOn
          ? t("refusal.windowClosed", { date: formatCalendarDate(locale, outcome.closedOn) })
          : t("refusal.windowClosedNoDate")
        : t(`refusal.${outcome.refusal}`);
    setProblem((now) => ({ text, n: (now?.n ?? 0) + 1 }));
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
      onClose={() => {
        if (changed) focusLineWhenRefreshed();
        props.onClose(changed);
      }}
      data-sheet=""
      data-declaration-sheet=""
      className={cn(sheetClass("lg"), "max-sm:max-h-[92dvh]")}
    >
      <SheetHandle />
      <h2 id={titleId} className="text-lg text-ink">
        {t("title")}
      </h2>
      <span aria-live="polite" className="sr-only">
        {busy ? t("submitting") : hashing ? t("hashing") : ""}
      </span>

      {recorded ? (
        <div data-declaration-receipt="" className="mt-4 flex flex-col gap-4">
          <h3 ref={receipt} tabIndex={-1} className="font-semibold text-ink focus-visible:outline-none">
            {t("receipt", { date: formatDay(locale, recorded.declared_at) })}
          </h3>
          <p
            data-hash=""
            className="rounded-control border border-line bg-field p-3 font-mono text-sm break-all text-ink"
          >
            {recorded.evidence_sha256_hex}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-ink-soft">{t("titleLabel")}</dt>
            <dd className="[overflow-wrap:anywhere] text-ink">{recorded.evidence_title}</dd>
            <dt className="text-ink-soft">{t("date")}</dt>
            <dd className="text-ink">{formatCalendarDate(locale, recorded.evidence_dated_on)}</dd>
          </dl>
          <p className="text-sm text-ink-soft">{t("told")}</p>
          <div className="flex justify-end">
            <Button
              variant="secondary"
              onClick={() => ref.current?.close()}
              className="w-full sm:w-auto"
              data-dialog-cancel=""
            >
              {t("done")}
            </Button>
          </div>
        </div>
      ) : (
        <form
          noValidate
          onSubmit={(event) => void submit(event)}
          data-declaration-form=""
          className="mt-3 flex flex-col gap-5"
        >
          <div className="flex max-w-[60ch] flex-col gap-2 text-ink">
            <p>{t("lead")}</p>
            <p>{t("private")}</p>
            <p className="font-semibold">{t("window", { date: closes })}</p>
          </div>

          <fieldset className="flex flex-col gap-3">
            <legend className="mb-1 font-semibold text-ink">{t("evidence")}</legend>
            <div className="grid grid-cols-2 overflow-hidden rounded-control border border-ink-soft">
              {(["file", "paste"] as const).map((value) => (
                <label
                  key={value}
                  htmlFor={`${id}-source-${value}`}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center justify-center border-l border-ink-soft px-2 text-center font-semibold text-ink first:border-l-0",
                    "has-checked:bg-accent has-checked:text-on-accent",
                    "has-focus-visible:outline-2 has-focus-visible:-outline-offset-4 has-focus-visible:outline-on-accent",
                  )}
                >
                  <input
                    id={`${id}-source-${value}`}
                    type="radio"
                    name={`${id}-source`}
                    value={value}
                    checked={source === value}
                    onChange={() => {
                      setSource(value);
                      setErrors((now) => ({ ...now, hash: undefined }));
                    }}
                    className="sr-only"
                    {...(value === "file" ? { "data-sheet-first": "" } : {})}
                  />
                  {value === "file" ? t("sourceFile") : t("sourcePaste")}
                </label>
              ))}
            </div>

            {source === "file" ? (
              <div className="flex flex-col gap-1.5">
                <label htmlFor={ids.file} className="font-medium text-ink">
                  {t("file")}
                </label>
                <p id={`${ids.file}-hint`} className="text-sm text-ink-soft">
                  {t("fileHint")}
                </p>
                {errors.hash ? <FieldError id={`${ids.file}-error`}>{errors.hash}</FieldError> : null}
                <input
                  id={ids.file}
                  type="file"
                  aria-describedby={cn(`${ids.file}-hint`, errors.hash && `${ids.file}-error`)}
                  aria-invalid={errors.hash ? true : undefined}
                  onChange={(event) => void choose(event.currentTarget.files?.[0])}
                  className={cn(
                    "min-h-11 w-full min-w-0 text-sm text-ink file:mr-3 file:min-h-11 file:cursor-pointer file:rounded-control",
                    "file:border file:border-ink-soft file:bg-field file:px-4 file:font-semibold file:text-ink hover:file:border-accent",
                  )}
                />
                <div aria-live="polite" data-fingerprint="" className="text-sm">
                  {file.kind === "hashing" ? <p className="text-ink-soft">{t("hashing")}</p> : null}
                  {file.kind === "done" ? (
                    <>
                      <p className="[overflow-wrap:anywhere] text-ink-soft">{t("hashed", { name: file.name })}</p>
                      <p className="mt-1 font-mono break-all text-ink" data-file-hash="">
                        {file.hash}
                      </p>
                    </>
                  ) : null}
                </div>
              </div>
            ) : (
              <TextField
                id={ids.hash}
                label={t("paste")}
                hint={t("pasteHint")}
                autoComplete="off"
                spellCheck={false}
                inputMode="text"
                maxLength={80}
                value={pasted}
                error={errors.hash}
                onChange={(event) => {
                  setPasted(event.currentTarget.value);
                  setErrors((now) => ({ ...now, hash: undefined }));
                }}
                onBlur={() => {
                  if (pasted.trim() && !asSha256(pasted)) setErrors((now) => ({ ...now, hash: t("invalidHash") }));
                }}
                className="font-mono text-sm"
              />
            )}
          </fieldset>

          <TextField
            id={ids.title}
            label={t("titleLabel")}
            hint={t("titleHint")}
            maxLength={TITLE_MAX}
            autoComplete="off"
            value={title}
            error={errors.title}
            onChange={(event) => {
              setTitle(event.currentTarget.value);
              setErrors((now) => ({ ...now, title: undefined }));
            }}
          />
          <TextField
            id={ids.date}
            type="date"
            label={t("date")}
            hint={t("dateHint", { date: firstView })}
            max={props.firstViewOn}
            value={dated}
            error={errors.date}
            onChange={(event) => {
              setDated(event.currentTarget.value);
              setErrors((now) => ({ ...now, date: undefined }));
            }}
            className="max-w-[14rem]"
          />

          {problem ? (
            <Alert key={problem.n} ref={problemRef} tone="error">
              {problem.text}
            </Alert>
          ) : null}

          {/* Cancel first, on top on phones and on the left from 640 px (the tracker's sheets' order); the send button
              is styled, not marked, as primary: the screen's data-primary stays on the page's own action. */}
          <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
            <Button variant="secondary" busy={busy} onClick={() => ref.current?.close()} data-dialog-cancel="">
              {t("cancel")}
            </Button>
            <button
              type="submit"
              aria-disabled={busy || hashing || undefined}
              data-dialog-confirm=""
              className={buttonClass("primary")}
            >
              {busy ? t("submitting") : t("submit")}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
