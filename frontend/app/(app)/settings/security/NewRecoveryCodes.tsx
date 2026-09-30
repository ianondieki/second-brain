"use client";

import { useTranslations } from "next-intl";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import { AccountUsername } from "@/components/ui/AccountUsername";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { PasswordField } from "@/components/ui/PasswordField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";

import { ErrorNotice } from "./ErrorNotice";
import { StepUpForm } from "./lazy";
import { renewalStep } from "./outcomes";
import { usePasswordState } from "./PasswordState";
import { RecoveryCodeList } from "./RecoveryCodeList";
import { reveal } from "./reveal";

// Loaded only after "Get new recovery codes" is pressed (React.lazy, see lazy.ts).

type Stage = { name: "confirm" } | { name: "stepUp" } | { name: "codes"; codes: string[] };

/** How long the request waits for an answer before saying it cannot tell whether the codes were replaced. */
const RENEW_TIMEOUT_MS = 10_000;

export interface NewRecoveryCodesProps {
  /** The account's email: the hidden username beside the password field, for password managers. */
  email: string;
  /** "Cancel", or "I have saved my codes": back to the "on" screen. */
  onClose: () => void;
  /** New codes were made: the old ones no longer work (and a "codes not shown" notice is settled). */
  onReplaced: () => void;
  /** 409 totp_not_enabled: two-step sign-in was turned off meanwhile, so there is nothing to replace. */
  onTwoStepOff: () => void;
}

/**
 * New recovery codes (POST /api/auth/totp/recovery-codes, REQ-AUTH-01 follow-up 8): the way to codes after setup's
 * answer was lost, or when the saved ones are gone. The API asks for the current password when the account has one
 * and a second factor within 12 hours: a stale one gets a code form (POST /api/auth/step-up), then the same request
 * again with the password already typed. The ten codes are shown once, as at setup.
 */
export function NewRecoveryCodes({ email, onClose, onReplaced, onTwoStepOff }: NewRecoveryCodesProps) {
  const t = useTranslations("security");
  const te = useTranslations("errors");
  const { hasPassword, markPasswordSet } = usePasswordState();

  const [stage, setStage] = useState<Stage>({ name: "confirm" });
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | undefined>();
  const [error, setError] = useState<ErrorKey | null>(null);
  // No answer, or one that cannot be read: the codes may have been replaced (fixed notice, not an errors.* key).
  const [unknown, setUnknown] = useState(false);
  const [busy, setBusy] = useState(false);
  const errorRef = useRef<HTMLDivElement>(null);
  const readyRef = useRef<HTMLDivElement>(null);

  // Opening the form moves focus into it: the password it asks for, else the button that makes the codes (which
  // reads the warning through aria-describedby).
  useEffect(() => {
    document.getElementById(hasPassword ? "renew-password" : "renew-submit")?.focus();
    // Only on opening: a password asked for later takes focus where it is asked for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function request() {
    setBusy(true);
    setError(null);
    setUnknown(false);
    setPasswordError(undefined);
    const step = renewalStep(
      await settle(
        api.POST("/api/auth/totp/recovery-codes", {
          body: { current_password: password || null },
          signal: AbortSignal.timeout(RENEW_TIMEOUT_MS),
        }),
      ),
    );
    switch (step.kind) {
      case "codes":
        // The codes replace everything above them: focus goes to the line that says the old ones stopped working.
        reveal(
          () => {
            setBusy(false);
            setPassword("");
            setStage({ name: "codes", codes: step.codes });
            onReplaced();
          },
          () => readyRef.current,
        );
        return;
      case "stepUp":
        setBusy(false);
        setStage({ name: "stepUp" }); // StepUpForm focuses its code field, then calls request again
        return;
      case "password":
        markPasswordSet(); // the account has a password after all: keep asking for it
        reveal(
          () => {
            setBusy(false);
            setPassword("");
            setStage({ name: "confirm" });
            setPasswordError(te("current_password_required"));
          },
          () => document.getElementById("renew-password"),
        );
        return;
      case "off":
        setBusy(false);
        onTwoStepOff();
        return;
      case "unknown":
        reveal(
          () => {
            setBusy(false);
            setStage({ name: "confirm" });
            setUnknown(true);
          },
          () => errorRef.current,
        );
        return;
      case "error":
        // Back to the form, the password kept: the step-up (if any) is done, so sending again is enough.
        reveal(
          () => {
            setBusy(false);
            setStage({ name: "confirm" });
            setError(step.key);
          },
          () => errorRef.current,
        );
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (hasPassword && !password) {
      setPasswordError(te("current_password_required"));
      document.getElementById("renew-password")?.focus();
      return;
    }
    await request();
  }

  if (stage.name === "codes") {
    return (
      <div className="flex w-full flex-col items-start gap-5">
        <Alert ref={readyRef} tone="ok">
          {t("newCodesReady")}
        </Alert>
        <p className="text-ink-soft">{t("codesLead")}</p>
        <RecoveryCodeList codes={stage.codes} />
        <Button variant="primary" onClick={onClose}>
          {t("done")}
        </Button>
      </div>
    );
  }

  const cancel = (
    <Button variant="link" busy={busy} onClick={onClose}>
      {t("cancelNewCodes")}
    </Button>
  );

  if (stage.name === "stepUp") {
    return (
      <div className="flex w-full flex-col items-start gap-4">
        <p id="renew-warning" className="text-ink">
          {t("newCodesWarning")}
        </p>
        <Suspense fallback={<p role="status" className="text-ink-soft">{t("loading")}</p>}>
          <StepUpForm
            onConfirmed={request}
            busyLabel={t("gettingCodes")}
            lead={t("newCodesStepUp")}
            submitLabel={t("newCodesStepUpSubmit")}
            variant="primary"
            describedBy="renew-warning"
          />
        </Suspense>
        {cancel}
      </div>
    );
  }

  return (
    <Form onSubmit={submit} className="flex w-full flex-col items-start gap-5">
      {unknown ? <Alert ref={errorRef}>{t("newCodesUnknown")}</Alert> : null}
      <ErrorNotice error={error} email={email} alertRef={errorRef} />
      <p id="renew-warning" className="text-ink">
        {t("newCodesWarning")}
      </p>
      {hasPassword ? (
        <div className="w-full">
          <AccountUsername email={email} />
          <PasswordField
            id="renew-password"
            name="current_password"
            label={t("currentPassword")}
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              setPasswordError(undefined);
            }}
            error={passwordError}
          />
        </div>
      ) : null}
      <div className="flex w-full flex-col items-start gap-2 sm:flex-row sm:items-center sm:gap-6">
        <SubmitButton id="renew-submit" variant="primary" busy={busy} aria-describedby="renew-warning">
          {busy ? t("gettingCodes") : t("newCodes")}
        </SubmitButton>
        {cancel}
      </div>
    </Form>
  );
}
