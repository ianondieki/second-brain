"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense, useState, type FormEvent } from "react";

import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { CheckIcon } from "@/components/ui/icons";
import { PasswordField } from "@/components/ui/PasswordField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { EnrolmentSteps, loadEnrolmentSteps, SignInAgain, StepUpForm } from "./lazy";
import { Steps } from "./Steps";

type Phase = { name: "intro" } | { name: "setup"; secret: string; otpauthUri: string } | { name: "on" };

export interface SecuritySettingsProps {
  enrolled: boolean;
  /** The person's role makes two-step sign-in mandatory: it cannot be turned off here. */
  required: boolean;
  homeHref: string;
  /** For "Email me a sign-in link" when an account without a password must sign in again first. */
  email: string;
}

export function SecuritySettings({ enrolled, required, homeHref, email }: SecuritySettingsProps) {
  const t = useTranslations("security");
  const tf = useTranslations("fields");
  const te = useTranslations("errors");

  const [phase, setPhase] = useState<Phase>(enrolled ? { name: "on" } : { name: "intro" });
  const [justTurnedOff, setJustTurnedOff] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [stepUp, setStepUp] = useState(false);

  /** Enrolment is a privilege change: the API asks for the current password (or a fresh sign-in without one). */
  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setPasswordError(undefined);
    setJustTurnedOff(false);
    const steps = loadEnrolmentSteps(); // fetch the next screen's code while the server works
    const outcome = await settle(api.POST("/api/auth/totp/enrol", { body: { password: password || null } }));
    if (!outcome.ok) {
      setBusy(false);
      if (outcome.key === "totp_already_enabled") {
        setPhase({ name: "on" });
      } else if (outcome.key === "current_password_required") {
        setPasswordError(te("current_password_required"));
        document.getElementById("enrol-password")?.focus();
      } else {
        setError(outcome.key);
      }
      return;
    }
    await steps.catch(() => undefined);
    setBusy(false);
    setPassword("");
    setPhase({ name: "setup", secret: outcome.data.secret, otpauthUri: outcome.data.otpauth_uri });
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
      setStepUp(true); // StepUpForm asks for a fresh code, then calls turnOff again
      return;
    }
    setError(outcome.key);
  }

  const errorBlock = (
    <>
      {error ? <Alert>{te(error)}</Alert> : null}
      {error === "recent_sign_in_required" ? (
        <Suspense fallback={null}>
          <SignInAgain email={email} />
        </Suspense>
      ) : null}
    </>
  );

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
            onRestart={(key) => {
              setError(key);
              setPhase({ name: "intro" });
            }}
          />
        </Suspense>
      </div>
    );
  }

  return (
    <div className="mt-8 flex flex-col gap-6">
      {justTurnedOff ? <Alert tone="info">{t("off")}</Alert> : null}
      {errorBlock}
      <Steps
        label={t("stepsLabel")}
        doneLabel={t("stepDone")}
        current={1}
        steps={[{ title: t("step1") }, { title: t("step2") }, { title: t("step3") }]}
      />
      <Form onSubmit={start} className="flex flex-col gap-5">
        <PasswordField
          id="enrol-password"
          name="password"
          label={t("currentPassword")}
          hint={t("currentPasswordHint")}
          autoComplete="current-password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            setPasswordError(undefined);
          }}
          error={passwordError}
          showLabel={tf("showPassword")}
          hideLabel={tf("hidePassword")}
          showName={tf("showPasswordName")}
          hideName={tf("hidePasswordName")}
        />
        <div>
          <SubmitButton variant="primary" busy={busy}>
            {busy ? t("starting") : t("start")}
          </SubmitButton>
        </div>
      </Form>
    </div>
  );
}
