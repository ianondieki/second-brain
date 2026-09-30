"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense, useRef, useState, type FormEvent } from "react";

import { AccountUsername } from "@/components/ui/AccountUsername";
import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { CheckIcon } from "@/components/ui/status-icons";
import { PasswordField } from "@/components/ui/PasswordField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { ErrorNotice } from "./ErrorNotice";
import { EnrolmentSteps, loadEnrolmentSteps, NewRecoveryCodes, StepUpForm } from "./lazy";
import { usePasswordState } from "./PasswordState";
import { reveal } from "./reveal";
import { Steps } from "./Steps";

type Phase = { name: "intro" } | { name: "setup"; secret: string; otpauthUri: string } | { name: "on" };
/**
 * What just happened, with the name the authenticator app shows for the entry where it matters: two-step sign-in
 * was turned off, its setup was cancelled (delete that entry), or it is on but the recovery codes never arrived
 * (keep that entry).
 */
type Notice = { key: "off" } | { key: "cancelled" | "codesNotShown"; product: string } | null;

/**
 * The issuer an authenticator app lists the account under: "Bridge" in otpauth://totp/Bridge:a%40b.c?issuer=Bridge.
 * The API takes it from its product name setting, so a rename reaches this line without a copy change.
 */
export function issuerOf(otpauthUri: string): string | null {
  try {
    return new URL(otpauthUri).searchParams.get("issuer")?.trim() || null;
  } catch {
    return null;
  }
}

export interface SecuritySettingsProps {
  enrolled: boolean;
  /** The person's role makes two-step sign-in mandatory: it cannot be turned off here. */
  required: boolean;
  homeHref: string;
  /**
   * The account's email: the hidden username beside the password field (for password managers), and the address for
   * "Email me a sign-in link" when an account without a password must sign in again first.
   */
  email: string;
  /** The product's name (the `app.name` brand token), for the cancelled notice if the setup key names no issuer. */
  productName: string;
}

export function SecuritySettings({ enrolled, required, homeHref, email, productName }: SecuritySettingsProps) {
  const t = useTranslations("security");
  const te = useTranslations("errors");

  const [phase, setPhase] = useState<Phase>(enrolled ? { name: "on" } : { name: "intro" });
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [stepUp, setStepUp] = useState(false);
  // "Get new recovery codes" is open (its form, step-up or the new codes) in place of the button that opens it.
  const [renewing, setRenewing] = useState(false);
  // What just happened (one notice at a time) and an API error: each takes focus when it appears after an action.
  const noticeRef = useRef<HTMLDivElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  // Without a password, enrolment needs a fresh sign-in instead; the flag is shared with the Password section.
  const { hasPassword, markPasswordSet, setEnrolling } = usePasswordState();

  /**
   * The setup steps hide the Password section; it comes back when they end (cancelled, restarted or left). New
   * recovery codes, a task of the "on" screen, end whenever the screen changes.
   */
  function show(next: Phase) {
    setPhase(next);
    setRenewing(false);
    setEnrolling(next.name === "setup");
  }

  /** Opens "Get new recovery codes": one task at a time, so turning off and the Password section step aside. */
  function openRenewal() {
    setError(null);
    setStepUp(false);
    setRenewing(true);
    setEnrolling(true);
  }

  /** Cancelled, or the new codes saved: back to the button that opened it, with focus on it. */
  function closeRenewal() {
    reveal(
      () => {
        setRenewing(false);
        setEnrolling(false);
      },
      () => document.getElementById("new-codes"),
    );
  }

  /**
   * Back to the start (setup cancelled, or the server lost it), with focus on what happened: the "cancelled" notice
   * or the error. They sit above the steps, off screen at 360 px after the long setup steps, and the next Tab reaches
   * where setup begins again (the password field when the account has one, else the start button), which takes
   * focus itself when there is nothing to read. The server's pending key is replaced on the next start.
   */
  function backToStart(nextError: ErrorKey | null, nextNotice: Notice) {
    reveal(
      () => {
        setError(nextError);
        setNotice(nextNotice);
        show({ name: "intro" });
      },
      () =>
        noticeRef.current ??
        errorRef.current ??
        document.getElementById(hasPassword ? "enrol-password" : "two-step-start"),
    );
  }

  /**
   * Two-step sign-in is on at the server, but the answer with the recovery codes was lost: the "on" screen, with focus
   * on the notice that says to keep the app entry and to get new recovery codes.
   */
  function onWithoutCodes(product: string) {
    reveal(
      () => {
        setError(null);
        setNotice({ key: "codesNotShown", product });
        show({ name: "on" });
      },
      () => noticeRef.current,
    );
  }

  /** Enrolment is a privilege change: the API asks for the current password (or a fresh sign-in without one). */
  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setPasswordError(undefined);
    setNotice(null);
    // Fetch the next screen's code while the server works; a failed fetch surfaces later through React.lazy.
    const steps = loadEnrolmentSteps().catch(() => undefined);
    const outcome = await settle(api.POST("/api/auth/totp/enrol", { body: { password: password || null } }));
    if (!outcome.ok) {
      setBusy(false);
      if (outcome.key === "totp_already_enabled") {
        show({ name: "on" });
      } else if (outcome.key === "current_password_required") {
        markPasswordSet(); // the account has a password after all: keep asking for it
        setPasswordError(te("current_password_required"));
        document.getElementById("enrol-password")?.focus();
      } else {
        setError(outcome.key);
      }
      return;
    }
    await steps;
    setBusy(false);
    setPassword("");
    show({ name: "setup", secret: outcome.data.secret, otpauthUri: outcome.data.otpauth_uri });
  }

  async function turnOff() {
    if (busy) return;
    setBusy(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/totp/disable"));
    if (outcome.ok) {
      // Focus on the "off" notice: the button that had it is gone, and the notice starts above the screen at 360 px.
      reveal(
        () => {
          setBusy(false);
          setStepUp(false);
          setNotice({ key: "off" });
          show({ name: "intro" });
        },
        () => noticeRef.current,
      );
      return;
    }
    setBusy(false);
    if (outcome.key === "step_up_required") {
      setStepUp(true); // StepUpForm asks for a fresh code, then calls turnOff again
      return;
    }
    setError(outcome.key);
  }

  const errorBlock = <ErrorNotice error={error} email={email} alertRef={errorRef} />;

  if (phase.name === "on") {
    return (
      <div className="mt-8 flex flex-col items-start gap-6">
        {errorBlock}
        <p className="inline-flex items-start gap-2 font-semibold text-ok">
          <CheckIcon className="mt-0.5 size-5 shrink-0" />
          {t("on")}
        </p>
        {notice?.key === "codesNotShown" ? (
          <Alert ref={noticeRef}>{t("codesNotShown", { product: notice.product })}</Alert>
        ) : null}
        {renewing ? null : required ? (
          <p className="text-ink-soft">{t("mandatory")}</p>
        ) : stepUp ? (
          <Suspense fallback={null}>
            <StepUpForm onConfirmed={turnOff} busyLabel={t("turningOff")} />
          </Suspense>
        ) : (
          <Button variant="secondary" busy={busy} onClick={turnOff}>
            {busy ? t("turningOff") : t("turnOff")}
          </Button>
        )}
        <section
          aria-labelledby="recovery-heading"
          className="flex w-full flex-col items-start gap-4 border-t border-line pt-6"
        >
          <h3 id="recovery-heading" className="text-base text-ink">
            {t("recoveryTitle")}
          </h3>
          {renewing ? (
            <Suspense fallback={null}>
              <NewRecoveryCodes
                email={email}
                onClose={closeRenewal}
                onReplaced={() => setNotice(null)}
                onTwoStepOff={() => backToStart("totp_not_enabled", null)}
              />
            </Suspense>
          ) : (
            <>
              <p className="text-ink-soft">{t("recoveryLead")}</p>
              <Button
                id="new-codes"
                // After a lost answer, getting codes is what the notice above asks for: the screen's one primary action.
                variant={notice?.key === "codesNotShown" ? "primary" : "secondary"}
                onClick={openRenewal}
              >
                {t("newCodes")}
              </Button>
            </>
          )}
        </section>
        <Link href={homeHref} className={textLinkClass}>
          {t("back")}
        </Link>
      </div>
    );
  }

  if (phase.name === "setup") {
    const entryName = issuerOf(phase.otpauthUri) ?? productName;
    return (
      <div className="mt-8">
        <Suspense fallback={<p role="status" className="text-ink-soft">{t("starting")}</p>}>
          <EnrolmentSteps
            secret={phase.secret}
            otpauthUri={phase.otpauthUri}
            homeHref={homeHref}
            entryName={entryName}
            onRestart={(key) => backToStart(key, null)}
            onCancel={() => backToStart(null, { key: "cancelled", product: entryName })}
            onEnrolled={() => onWithoutCodes(entryName)}
          />
        </Suspense>
      </div>
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-6">
      {notice?.key === "off" ? (
        <Alert ref={noticeRef} tone="info">
          {t("off")}
        </Alert>
      ) : null}
      {notice?.key === "cancelled" ? (
        <Alert ref={noticeRef} tone="info">
          {t("cancelled", { product: notice.product })}
        </Alert>
      ) : null}
      {errorBlock}
      <Steps
        label={t("stepsLabel")}
        doneLabel={t("stepDone")}
        current={1}
        steps={[{ title: t("step1") }, { title: t("step2") }, { title: t("step3") }]}
      />
      <Form onSubmit={start} className="flex flex-col gap-5">
        {hasPassword ? (
          <>
            <AccountUsername email={email} />
            <PasswordField
              id="enrol-password"
              name="password"
              label={t("currentPassword")}
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setPasswordError(undefined);
              }}
              error={passwordError}
            />
          </>
        ) : null}
        <div>
          <SubmitButton id="two-step-start" variant="primary" busy={busy}>
            {busy ? t("starting") : t("start")}
          </SubmitButton>
        </div>
      </Form>
    </div>
  );
}
