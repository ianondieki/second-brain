"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense, useState, type FormEvent } from "react";

import { AccountUsername } from "@/components/ui/AccountUsername";
import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { CheckIcon } from "@/components/ui/icons";
import { PasswordField } from "@/components/ui/PasswordField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { ErrorNotice } from "./ErrorNotice";
import { EnrolmentSteps, loadEnrolmentSteps, StepUpForm } from "./lazy";
import { usePasswordState } from "./PasswordState";
import { Steps } from "./Steps";

type Phase = { name: "intro" } | { name: "setup"; secret: string; otpauthUri: string } | { name: "on" };
/**
 * An info line at the start: two-step sign-in was just turned off, or its setup was cancelled (with the name the
 * authenticator app shows for the entry to delete).
 */
type Notice = { key: "off" } | { key: "cancelled"; issuer: string | null } | null;

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
  // Without a password, enrolment needs a fresh sign-in instead; the flag is shared with the Password section.
  const { hasPassword, markPasswordSet, setEnrolling } = usePasswordState();

  /** The setup steps hide the Password section; it comes back when they end (cancelled, restarted or left). */
  function show(next: Phase) {
    setPhase(next);
    setEnrolling(next.name === "setup");
  }

  /**
   * Back to the start (setup cancelled, or the server lost it), with focus where setup begins again: the password
   * field when the account has one, else the start button. The server's pending key is replaced on the next start.
   */
  function backToStart(nextError: ErrorKey | null, nextNotice: Notice) {
    setError(nextError);
    setNotice(nextNotice);
    show({ name: "intro" });
    requestAnimationFrame(() => document.getElementById(hasPassword ? "enrol-password" : "two-step-start")?.focus());
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
    setBusy(false);
    if (outcome.ok) {
      setStepUp(false);
      setNotice({ key: "off" });
      show({ name: "intro" });
      return;
    }
    if (outcome.key === "step_up_required") {
      setStepUp(true); // StepUpForm asks for a fresh code, then calls turnOff again
      return;
    }
    setError(outcome.key);
  }

  const errorBlock = <ErrorNotice error={error} email={email} />;

  if (phase.name === "on") {
    return (
      <div className="mt-8 flex flex-col items-start gap-6">
        {errorBlock}
        <p className="inline-flex items-start gap-2 font-semibold text-ok">
          <CheckIcon className="mt-0.5 size-5 shrink-0" />
          {t("on")}
        </p>
        {required ? (
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
        <Link href={homeHref} className={textLinkClass}>
          {t("back")}
        </Link>
      </div>
    );
  }

  if (phase.name === "setup") {
    return (
      <div className="mt-8">
        <Suspense fallback={<p role="status" className="text-ink-soft">{t("starting")}</p>}>
          <EnrolmentSteps
            secret={phase.secret}
            otpauthUri={phase.otpauthUri}
            homeHref={homeHref}
            onRestart={(key) => backToStart(key, null)}
            onCancel={() => backToStart(null, { key: "cancelled", issuer: issuerOf(phase.otpauthUri) })}
          />
        </Suspense>
      </div>
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-6">
      {notice ? (
        <Alert tone="info">
          {notice.key === "off" ? t("off") : t("cancelled", { product: notice.issuer ?? productName })}
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
