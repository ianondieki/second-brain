"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { OtpInput } from "@/components/ui/OtpInput";

import { confirmStepUp } from "./calls";

export interface StepUpProps {
  /** Two-step sign-in is on for this account; without it there is no code to give, only the way to turn it on. */
  enrolled: boolean;
  /** Retries the step that asked for the fresh code (once). */
  onConfirmed: () => Promise<void>;
  onCancel: () => void;
  confirmImpl?: typeof confirmStepUp;
  /** Confirm is the screen's primary action (default); false when another primary button is on the screen. */
  primary?: boolean;
}

/**
 * The fresh second factor a signature, endorsement or payment asks for (403 step_up_required; ADR-002: an
 * authenticator code within 12 hours), inline where the button was: the code, then the step runs again. Like the
 * security settings' StepUpForm, with the tracker's server-formatted strings instead of next-intl's client runtime.
 */
export function StepUp({ enrolled, onConfirmed, onCancel, confirmImpl = confirmStepUp, primary = true }: StepUpProps) {
  const t = useStrings("trackerActions");
  // Its own id: the step-up appears on the tracker and on the scout match page, never twice with one id.
  const codeId = `${useId()}-step-up-code`;
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  // A code confirmed after the form has gone (the page moved on) must not run the step.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    document.getElementById(codeId)?.focus();
    return () => {
      mounted.current = false;
    };
  }, [codeId]);

  if (!enrolled) {
    return (
      <div data-step-up="enrol" className="flex flex-col items-start gap-3">
        <p className="max-w-[60ch] text-ink">{t("stepUp.notEnrolled")}</p>
        <Link href="/settings/security" className={standaloneLinkClass}>
          {t("stepUp.turnOn")}
        </Link>
        <Button variant="link" onClick={onCancel}>
          {t("cancel")}
        </Button>
      </div>
    );
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(t("stepUp.invalid"));
      document.getElementById(codeId)?.focus();
      return;
    }
    setBusy(true);
    setFailed(false);
    const outcome = await confirmImpl(code);
    if (!mounted.current) return;
    if (!outcome.ok) {
      setBusy(false);
      setCode("");
      if (outcome.invalidCode) {
        setCodeError(t("stepUp.invalid"));
        document.getElementById(codeId)?.focus();
      } else {
        setFailed(true);
      }
      return;
    }
    try {
      await onConfirmed();
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <Form onSubmit={confirm} data-step-up="code" className="flex flex-col items-start gap-4">
      {failed ? <Alert className="w-full">{t("refusal.generic")}</Alert> : null}
      <p className="max-w-[60ch] text-ink">{t("stepUp.body")}</p>
      <OtpInput
        id={codeId}
        name="code"
        label={t("stepUp.code")}
        value={code}
        onChange={(value) => {
          setCode(value);
          setCodeError(undefined);
        }}
        error={codeError}
      />
      <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
        <SubmitButton variant={primary ? "primary" : "secondary"} busy={busy}>
          {busy ? t("stepUp.checking") : t("stepUp.submit")}
        </SubmitButton>
        {/* Inert while the code is checked: the step may already be running. */}
        <Button variant="secondary" busy={busy} onClick={onCancel}>
          {t("cancel")}
        </Button>
      </div>
    </Form>
  );
}
