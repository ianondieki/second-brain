"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Form, SubmitButton } from "@/components/ui/Form";
import { OtpInput } from "@/components/ui/OtpInput";
import { api } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/errors";

export interface StepUpStrings {
  lead: string;
  code: string;
  submit: string;
  checking: string;
  invalid: string;
  failed: string;
}

/**
 * The step-up the Tier-2 predicate asks for when the session's second factor is older than 12 hours
 * (step_up_required): a fresh authenticator code (POST /api/auth/step-up), then the page is fetched again and shows
 * the step it now needs. Confirm is the screen's one primary action.
 */
export function StepUp({ strings }: { strings: StepUpStrings }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (code.length !== 6) {
      setCodeError(strings.invalid);
      document.getElementById("step-up-code")?.focus();
      return;
    }
    setBusy(true);
    setFailed(false);
    try {
      const { response, error } = await api.POST("/api/auth/step-up", { body: { code } });
      if (response.ok) {
        router.refresh();
        return;
      }
      setCode("");
      if (apiErrorCode(error) === "invalid_code") {
        setCodeError(strings.invalid);
        document.getElementById("step-up-code")?.focus();
      } else {
        setFailed(true);
      }
    } catch {
      setFailed(true);
    }
    setBusy(false);
  }

  return (
    <Form onSubmit={confirm} className="flex flex-col items-start gap-4">
      {failed ? (
        <Alert className="w-full" tone="error">
          {strings.failed}
        </Alert>
      ) : null}
      <p className="max-w-[60ch] text-ink" data-refusal="step_up_required">
        {strings.lead}
      </p>
      <OtpInput
        id="step-up-code"
        name="code"
        label={strings.code}
        value={code}
        onChange={(value) => {
          setCode(value);
          setCodeError(undefined);
        }}
        error={codeError}
      />
      <SubmitButton variant="primary" busy={busy}>
        {busy ? strings.checking : strings.submit}
      </SubmitButton>
    </Form>
  );
}
