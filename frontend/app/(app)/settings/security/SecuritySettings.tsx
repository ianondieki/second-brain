"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useRef, useState, type FormEvent, type ReactNode } from "react";

import { QrCode } from "@/components/QrCode";
import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon } from "@/components/ui/icons";
import { OtpInput } from "@/components/ui/OtpInput";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

type Phase =
  | { name: "intro" }
  | { name: "setup"; secret: string; qr: boolean[][] | null }
  | { name: "codes"; codes: string[] }
  | { name: "on" };

type Notice = "keyCopied" | "codesCopied" | "copyFailed" | null;

export interface SecuritySettingsProps {
  enrolled: boolean;
  /** The person's role makes two-step sign-in mandatory: it cannot be turned off here. */
  required: boolean;
  homeHref: string;
}

/** "ABCDEFGHIJKL" -> ["ABCD", "EFGH", "IJKL"]: easier to type into an authenticator app by hand. */
function keyGroups(secret: string) {
  return secret.match(/.{1,4}/g) ?? [secret];
}

async function qrMatrix(uri: string): Promise<boolean[][] | null> {
  try {
    // Loaded only when setup starts, so the QR encoder is not in the page's first download.
    const { encode } = await import("uqr");
    return encode(uri, { ecc: "M", border: 0 }).data;
  } catch {
    return null; // the key below still works without the picture
  }
}

export function SecuritySettings({ enrolled, required, homeHref }: SecuritySettingsProps) {
  const t = useTranslations("security");
  const tv = useTranslations("validation");
  const te = useTranslations("errors");
  const router = useRouter();
  const stepHeading = useRef<HTMLHeadingElement>(null);

  const [phase, setPhase] = useState<Phase>(enrolled ? { name: "on" } : { name: "intro" });
  const [justTurnedOff, setJustTurnedOff] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [codeFocused, setCodeFocused] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [stepUp, setStepUp] = useState(false);

  const current = phase.name === "codes" ? 3 : phase.name === "setup" && codeFocused ? 2 : 1;

  function focusStep() {
    requestAnimationFrame(() => stepHeading.current?.focus());
  }

  async function copy(text: string, done: Exclude<Notice, "copyFailed" | null>) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(done);
    } catch {
      setNotice("copyFailed");
    }
  }

  async function start() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setJustTurnedOff(false);
    const outcome = await settle(api.POST("/api/auth/totp/enrol"));
    if (!outcome.ok) {
      setBusy(false);
      if (outcome.key === "totp_already_enabled") setPhase({ name: "on" });
      else setError(outcome.key);
      return;
    }
    const qr = await qrMatrix(outcome.data.otpauth_uri);
    setBusy(false);
    setCode("");
    setPhase({ name: "setup", secret: outcome.data.secret, qr });
    focusStep();
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(tv("code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/totp/confirm", { body: { code } }));
    setBusy(false);
    if (outcome.ok) {
      setNotice(null);
      setPhase({ name: "codes", codes: outcome.data.recovery_codes });
      focusStep();
      return;
    }
    if (outcome.key === "invalid_code") {
      setCode("");
      setCodeError(te("invalid_code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    if (outcome.key === "no_pending_enrolment") setPhase({ name: "intro" });
    setError(outcome.key);
  }

  function download(codes: string[]) {
    const url = URL.createObjectURL(new Blob([`${codes.join("\n")}\n`], { type: "text/plain" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "recovery-codes.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function turnOff() {
    if (busy) return;
    setBusy(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/totp/disable"));
    setBusy(false);
    if (outcome.ok) {
      setStepUp(false);
      setJustTurnedOff(true);
      setPhase({ name: "intro" });
      return;
    }
    if (outcome.key === "step_up_required") {
      setStepUp(true);
      setCode("");
      requestAnimationFrame(() => document.getElementById("totp-code")?.focus());
      return;
    }
    setError(outcome.key);
  }

  async function confirmStepUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(tv("code"));
      document.getElementById("totp-code")?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/step-up", { body: { code } }));
    setBusy(false);
    if (!outcome.ok) {
      setCode("");
      if (outcome.key === "invalid_code") setCodeError(te("invalid_code"));
      else setError(outcome.key);
      return;
    }
    await turnOff();
  }

  const codeField = (
    <OtpInput
      id="totp-code"
      name="code"
      label={t("code")}
      value={code}
      onChange={(value) => {
        setCode(value);
        setCodeError(undefined);
      }}
      onFocus={() => setCodeFocused(true)}
      error={codeError}
    />
  );

  const noticeLine = (
    <p role="status" className="min-h-6 text-sm font-medium text-ink-soft">
      {notice ? (
        <span className={cn("inline-flex items-center gap-1.5", notice === "copyFailed" ? "text-error" : "text-ok")}>
          {notice === "copyFailed" ? <InfoIcon className="size-5" /> : <CheckIcon className="size-5" />}
          {t(notice)}
        </span>
      ) : null}
    </p>
  );

  if (phase.name === "on") {
    return (
      <div className="mt-8 flex flex-col items-start gap-6">
        {error ? <Alert>{te(error)}</Alert> : null}
        <p className="inline-flex items-start gap-2 font-semibold text-ok">
          <CheckIcon className="mt-0.5 size-5 shrink-0" />
          {t("on")}
        </p>
        {required ? (
          <p className="text-ink-soft">{t("mandatory")}</p>
        ) : stepUp ? (
          <form noValidate onSubmit={confirmStepUp} className="flex w-full flex-col items-start gap-4">
            <p className="text-ink">{t("stepUp")}</p>
            {codeField}
            <Button type="submit" variant="secondary" busy={busy}>
              {busy ? t("turningOff") : t("stepUpSubmit")}
            </Button>
          </form>
        ) : (
          <Button variant="secondary" busy={busy} onClick={turnOff}>
            {busy ? t("turningOff") : t("turnOff")}
          </Button>
        )}
        <Link href={homeHref} className={textLinkClass}>
          {t("back")}
        </Link>
      </div>
    );
  }

  const steps: Array<{ n: 1 | 2 | 3; title: string; body: ReactNode }> = [
    {
      n: 1,
      title: t("step1"),
      body:
        phase.name === "setup" ? (
          <div className="flex flex-col gap-5">
            <p className="text-ink-soft">{t("step1Body")}</p>
            {phase.qr ? <QrCode matrix={phase.qr} label={t("qrLabel")} /> : null}
            <dl className="flex flex-col gap-1">
              <dt className="font-medium text-ink">{t("key")}</dt>
              <dd data-testid="totp-key" className="code-figures text-base font-semibold text-ink sm:text-lg">
                {/* Wraps only between groups of four, never inside one. */}
                {keyGroups(phase.secret).map((group, index) => (
                  <Fragment key={index}>
                    {index > 0 ? " " : null}
                    <span className="whitespace-nowrap">{group}</span>
                  </Fragment>
                ))}
              </dd>
            </dl>
            <div className="flex flex-col items-start gap-1">
              <Button variant="secondary" onClick={() => copy(phase.secret, "keyCopied")}>
                {t("copyKey")}
              </Button>
              {noticeLine}
            </div>
          </div>
        ) : null,
    },
    {
      n: 2,
      title: t("step2"),
      body:
        phase.name === "setup" ? (
          <form noValidate onSubmit={confirm} className="flex flex-col items-start gap-5">
            {codeField}
            <Button type="submit" variant="primary" busy={busy}>
              {busy ? t("confirming") : t("confirm")}
            </Button>
          </form>
        ) : null,
    },
    {
      n: 3,
      title: t("step3"),
      body:
        phase.name === "codes" ? (
          <div className="flex flex-col items-start gap-5">
            <p className="text-ink-soft">{t("codesLead")}</p>
            <div className="w-full">
              <h3 id="codes-label" className="text-base font-medium">
                {t("codesLabel")}
              </h3>
              <ul
                aria-labelledby="codes-label"
                data-testid="recovery-codes"
                className={
                  "code-figures mt-2 grid grid-cols-[repeat(auto-fill,minmax(8.5rem,1fr))] gap-x-4 gap-y-1.5 " +
                  "border border-line bg-field px-4 py-3 text-base font-semibold text-ink sm:text-lg"
                }
              >
                {phase.codes.map((recovery) => (
                  <li key={recovery} className="whitespace-nowrap">
                    {recovery}
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => copy(phase.codes.join("\n"), "codesCopied")}>
                {t("copyCodes")}
              </Button>
              <Button variant="secondary" onClick={() => download(phase.codes)}>
                {t("download")}
              </Button>
            </div>
            {noticeLine}
            <Button variant="primary" onClick={() => router.push(homeHref)}>
              {t("done")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="mt-8 flex flex-col gap-6">
      {justTurnedOff ? <Alert tone="info">{t("off")}</Alert> : null}
      {error ? <Alert>{te(error)}</Alert> : null}
      <ol aria-label={t("stepsLabel")} className="flex flex-col">
        {steps.map((step) => {
          const isCurrent = step.n === current;
          const isDone = step.n < current;
          return (
            <li
              key={step.n}
              aria-current={isCurrent ? "step" : undefined}
              className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-x-4 pb-8 last:pb-0"
            >
              {step.n < steps.length ? (
                // The rail between one step marker and the next.
                <span aria-hidden="true" className="absolute top-9 bottom-1 left-[calc(1rem-0.5px)] w-px bg-line" />
              ) : null}
              <span
                aria-hidden="true"
                className={cn(
                  "relative flex size-8 items-center justify-center rounded-full text-sm font-semibold",
                  isCurrent && "bg-jacaranda text-white",
                  isDone && "bg-ok text-white",
                  !isCurrent && !isDone && "border border-ink-soft bg-paper text-ink-soft",
                )}
              >
                {isDone ? <CheckIcon className="size-5" /> : step.n}
              </span>
              <div className="flex min-w-0 flex-col gap-4 pt-1">
                <h2
                  ref={isCurrent ? stepHeading : undefined}
                  tabIndex={isCurrent ? -1 : undefined}
                  className={cn("text-base focus:outline-none", isCurrent ? "text-ink" : "text-ink-soft")}
                >
                  {step.title}
                  {isDone ? <span className="sr-only"> ({t("stepDone")})</span> : null}
                </h2>
                {step.body}
              </div>
            </li>
          );
        })}
      </ol>
      {phase.name === "intro" ? (
        <div>
          <Button variant="primary" busy={busy} onClick={start}>
            {busy ? t("starting") : t("start")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
