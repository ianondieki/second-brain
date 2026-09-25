"use client";

import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { PasswordField } from "@/components/ui/PasswordField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { PASSWORD_MAX, PASSWORD_MIN } from "@/lib/auth/password";

import { ErrorNotice } from "./ErrorNotice";
import { usePasswordState } from "./PasswordState";

/**
 * Set or change the password (POST /api/auth/password). Needed, for example, after a verification link opened in
 * another browser cleared a password set at signup. The current password is required when one is set; an account
 * without one needs a sign-in in the last 15 minutes.
 */
export function PasswordSettings({ email }: { email: string }) {
  const t = useTranslations("password");
  const tf = useTranslations("fields");
  const tv = useTranslations("validation");
  const ts = useTranslations("signup");
  const te = useTranslations("errors");
  const summaryRef = useRef<HTMLDivElement>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [currentError, setCurrentError] = useState<string | undefined>();
  const [nextError, setNextError] = useState<string | undefined>();
  const [error, setError] = useState<ErrorKey | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  // The account has a password (from the API, or since one was saved here): changing it needs the current one.
  const { hasPassword, markPasswordSet } = usePasswordState();

  const toggle = {
    showLabel: tf("showPassword"),
    hideLabel: tf("hidePassword"),
    showName: tf("showPasswordName"),
    hideName: tf("hidePasswordName"),
  };

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setSaved(false);
    setError(null);
    setCurrentError(undefined);
    if (!next) {
      setNextError(tv("password"));
      document.getElementById("new-password")?.focus();
      return;
    }
    if (next.length < PASSWORD_MIN || next.length > PASSWORD_MAX) {
      setNextError(tv("passwordLength"));
      document.getElementById("new-password")?.focus();
      return;
    }
    setNextError(undefined);
    setBusy(true);
    const outcome = await settle(
      api.POST("/api/auth/password", { body: { current_password: current || null, new_password: next } }),
    );
    setBusy(false);
    if (outcome.ok) {
      setCurrent("");
      setNext("");
      setSaved(true);
      markPasswordSet();
      return;
    }
    if (outcome.key === "current_password_required") {
      markPasswordSet();
      setCurrentError(te("current_password_required"));
      document.getElementById("password-current")?.focus();
      return;
    }
    if (outcome.key === "weak_password") {
      setNextError(te("weak_password"));
      document.getElementById("new-password")?.focus();
      return;
    }
    setError(outcome.key);
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  return (
    <section id="password" aria-labelledby="password-heading" className="mt-12 scroll-mt-8 border-t border-line pt-8">
      <h2 id="password-heading" className="text-lg text-ink">
        {t("title")}
      </h2>
      <p className="mt-2 text-ink-soft">{t("lead")}</p>
      <Form onSubmit={save} className="mt-6 flex flex-col gap-5">
        {saved ? <Alert tone="ok">{t("saved")}</Alert> : null}
        <ErrorNotice error={error} email={email} alertRef={summaryRef} />
        {hasPassword ? (
          <PasswordField
            id="password-current"
            name="current_password"
            label={t("current")}
            autoComplete="current-password"
            value={current}
            onChange={(event) => {
              setCurrent(event.target.value);
              setCurrentError(undefined);
            }}
            error={currentError}
            {...toggle}
          />
        ) : null}
        <PasswordField
          id="new-password"
          name="new_password"
          label={t("new")}
          hint={ts("passwordHint")}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          value={next}
          onChange={(event) => {
            setNext(event.target.value);
            setNextError(undefined);
          }}
          error={nextError}
          {...toggle}
        />
        <div>
          <SubmitButton variant="secondary" busy={busy}>
            {busy ? t("saving") : t("save")}
          </SubmitButton>
        </div>
      </Form>
    </section>
  );
}
