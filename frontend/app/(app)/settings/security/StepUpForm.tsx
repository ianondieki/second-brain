"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { Form, SubmitButton } from "@/components/ui/Form";
import { OtpInput } from "@/components/ui/OtpInput";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { ErrorNotice } from "./ErrorNotice";

// Loaded only when turning two-step sign-in off asks for a fresh code (403 step_up_required).

/** A fresh second factor (POST /api/auth/step-up), then `onConfirmed` retries the action that asked for it. */
export function StepUpForm({ onConfirmed, busyLabel }: { onConfirmed: () => Promise<void>; busyLabel: string }) {
  const t = useTranslations("security");
  const tv = useTranslations("validation");
  const te = useTranslations("errors");
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string | undefined>();
  const [error, setError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.getElementById("totp-code")?.focus();
  }, []);

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
    const outcome = await settle(api.POST("/api/auth/step-up", { body: { code } }));
    if (!outcome.ok) {
      setBusy(false);
      setCode("");
      if (outcome.key === "invalid_code") setCodeError(te("invalid_code"));
      else setError(outcome.key);
      return;
    }
    try {
      await onConfirmed();
    } finally {
      setBusy(false); // whatever onConfirmed decides, the form must not stay stuck on "Turning off…"
    }
  }

  return (
    <Form onSubmit={confirm} className="flex w-full flex-col items-start gap-4">
      <ErrorNotice error={error} />
      <p className="text-ink">{t("stepUp")}</p>
      <OtpInput
        id="totp-code"
        name="code"
        label={t("code")}
        value={code}
        onChange={(value) => {
          setCode(value);
          setCodeError(undefined);
        }}
        error={codeError}
      />
      <SubmitButton variant="secondary" busy={busy}>
        {busy ? busyLabel : t("stepUpSubmit")}
      </SubmitButton>
    </Form>
  );
}
