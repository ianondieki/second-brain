"use client";

import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

import { AccountUsername } from "@/components/ui/AccountUsername";
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
  // While two-step setup is on screen this section is hidden, not unmounted, so anything typed here is kept.
  const { hasPassword, markPasswordSet, enrolling } = usePasswordState();

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
    // Section's markup (h2 20 px, one-line description, content 16 px below; no rule), written out here rather than
    // imported: this page is within a few hundred bytes of the 150 KB budget (docs/spec/07 item 5; P16-C1 card).
    <section id="password" aria-labelledby="password-heading" hidden={enrolling} className="mt-12 scroll-mt-8">
      <h2 id="password-heading" className="text-lg text-ink">
        {t("title")}
      </h2>
      <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{t("lead")}</p>
      <Form onSubmit={save} className="mt-4 flex flex-col gap-5">
        <AccountUsername email={email} />
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
