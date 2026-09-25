"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { OtpInput } from "@/components/ui/OtpInput";
import { TextField } from "@/components/ui/TextField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { continueAfterSignIn } from "@/lib/auth/session";

/** Second step of sign-in: a code from the authenticator app, or one recovery code. */
export function MfaForm() {
  const t = useTranslations();
  const router = useRouter();
  const summaryRef = useRef<HTMLDivElement>(null);
  const [useRecovery, setUseRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [serverError, setServerError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState(false);

  const fieldId = useRecovery ? "recovery-code" : "code";

  function switchMode() {
    setUseRecovery((value) => !value);
    setFieldError(undefined);
    setServerError(null);
    requestAnimationFrame(() => document.getElementById(useRecovery ? "code" : "recovery-code")?.focus());
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setServerError(null);
    const value = useRecovery ? recoveryCode.trim() : code;
    const invalid = useRecovery ? value.length < 6 : value.length !== 6;
    if (invalid) {
      setFieldError(t(useRecovery ? "validation.recoveryCode" : "validation.code"));
      document.getElementById(fieldId)?.focus();
      return;
    }
    setFieldError(undefined);
    setBusy(true);
    const outcome = await settle(api.POST("/api/auth/mfa/verify", { body: { code: value } }));
    if (outcome.ok) {
      await continueAfterSignIn(router, false);
      return;
    }
    setBusy(false);
    if (outcome.key === "unauthenticated") {
      router.replace("/login");
      return;
    }
    setServerError(outcome.key);
    if (outcome.key === "invalid_code") {
      setCode("");
      setRecoveryCode("");
    }
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  return (
    <form noValidate onSubmit={submit} className="mt-8 flex flex-col gap-6">
      {serverError ? <Alert ref={summaryRef}>{t(`errors.${serverError}`)}</Alert> : null}
      {useRecovery ? (
        <TextField
          id="recovery-code"
          name="recovery_code"
          label={t("mfa.recovery")}
          hint={t("mfa.recoveryHint")}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          className="code-figures max-w-[16rem]"
          value={recoveryCode}
          onChange={(event) => {
            setRecoveryCode(event.target.value);
            setFieldError(undefined);
          }}
          error={fieldError}
        />
      ) : (
        <OtpInput
          id="code"
          name="code"
          label={t("mfa.code")}
          value={code}
          onChange={(value) => {
            setCode(value);
            setFieldError(undefined);
          }}
          error={fieldError}
        />
      )}
      <div className="flex flex-col items-start gap-2">
        <Button type="submit" variant="primary" busy={busy}>
          {busy ? t("mfa.submitting") : t("mfa.submit")}
        </Button>
        <Button variant="link" onClick={switchMode} aria-controls={fieldId}>
          {useRecovery ? t("mfa.useApp") : t("mfa.useRecovery")}
        </Button>
      </div>
    </form>
  );
}
