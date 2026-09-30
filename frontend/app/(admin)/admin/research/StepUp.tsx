"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { OtpInput } from "@/components/ui/OtpInput";

import { confirmStepUp } from "./calls";

export interface StepUpProps {
  /** Runs once the fresh code is accepted: fetch the page again, or repeat the action that asked for it. */
  onConfirmed: () => void | Promise<void>;
  /** Shown as "Cancel" when given (inline, where an action asked for the code). */
  onCancel?: () => void;
  confirmImpl?: typeof confirmStepUp;
}

/**
 * The fresh second factor the staff console asks for when the last one is older than 12 hours (403
 * step_up_required; ADR-002): a code from the authenticator app, then the page or the action carries on. Confirm is
 * the one primary action while it is shown. Why the code is asked for is the field's hint (aria-describedby).
 */
export function StepUp({ onConfirmed, onCancel, confirmImpl = confirmStepUp }: StepUpProps) {
  const t = useStrings("adminResearch");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    document.getElementById("admin-step-up-code")?.focus();
    return () => {
      mounted.current = false;
    };
  }, []);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(t("stepUp.invalid"));
      document.getElementById("admin-step-up-code")?.focus();
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
        document.getElementById("admin-step-up-code")?.focus();
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
    <Form onSubmit={confirm} data-step-up="" className="flex flex-col items-start gap-4">
      {failed ? <Alert className="w-full">{t("refusal.generic")}</Alert> : null}
      <OtpInput
        id="admin-step-up-code"
        name="code"
        label={t("stepUp.code")}
        hint={<span data-refusal="step_up_required">{t("stepUp.body")}</span>}
        value={code}
        onChange={(value) => {
          setCode(value);
          setCodeError(undefined);
        }}
        error={codeError}
      />
      <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
        <SubmitButton variant="primary" busy={busy}>
          {busy ? t("stepUp.checking") : t("stepUp.submit")}
        </SubmitButton>
        {onCancel ? (
          <Button variant="secondary" busy={busy} onClick={onCancel}>
            {t("stepUp.cancel")}
          </Button>
        ) : null}
      </div>
    </Form>
  );
}
