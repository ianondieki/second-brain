"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { PasswordField } from "@/components/ui/PasswordField";
import { TextField } from "@/components/ui/TextField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { continueAfterSignIn, rememberEmail } from "@/lib/auth/session";
import { checkEmail, validateLogin, type LoginValues } from "@/lib/auth/validation";

type Busy = "login" | "link" | null;

export function LoginForm() {
  const t = useTranslations();
  const router = useRouter();
  const summaryRef = useRef<HTMLDivElement>(null);
  const [values, setValues] = useState<LoginValues>({ email: "", password: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof LoginValues, string>>>({});
  const [serverError, setServerError] = useState<ErrorKey | null>(null);
  const [busy, setBusy] = useState<Busy>(null);

  function set(key: keyof LoginValues, value: string) {
    setValues((current) => ({ ...current, [key]: value }));
    if (errors[key]) setErrors((current) => ({ ...current, [key]: undefined }));
  }

  function showServerError(key: ErrorKey) {
    setServerError(key);
    requestAnimationFrame(() => summaryRef.current?.focus());
  }

  async function logIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setServerError(null);
    const invalid = validateLogin(values);
    setErrors({
      email: invalid.email && t(`validation.${invalid.email}`),
      password: invalid.password && t(`validation.${invalid.password}`),
    });
    if (invalid.email || invalid.password) {
      document.getElementById(invalid.email ? "email" : "password")?.focus();
      return;
    }
    setBusy("login");
    const outcome = await settle(
      api.POST("/api/auth/login", { body: { email: values.email.trim(), password: values.password } }),
    );
    if (outcome.ok) {
      await continueAfterSignIn(router, outcome.data.mfa_required);
      return;
    }
    setBusy(null);
    showServerError(outcome.key);
  }

  async function emailLink() {
    if (busy) return;
    setServerError(null);
    const invalid = checkEmail(values.email, "emailForLink");
    setErrors({ email: invalid && t(`validation.${invalid}`) });
    if (invalid) {
      document.getElementById("email")?.focus();
      return;
    }
    setBusy("link");
    const email = values.email.trim();
    const outcome = await settle(api.POST("/api/auth/magic-link", { body: { email } }));
    if (outcome.ok) {
      rememberEmail(email);
      router.push("/signup/check-email?for=login");
      return;
    }
    setBusy(null);
    showServerError(outcome.key);
  }

  return (
    <Form onSubmit={logIn} className="mt-8 flex flex-col gap-6">
      {serverError ? <Alert ref={summaryRef}>{t(`errors.${serverError}`)}</Alert> : null}

      <TextField
        id="email"
        name="email"
        type="email"
        label={t("fields.email")}
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        value={values.email}
        onChange={(event) => set("email", event.target.value)}
        error={errors.email}
      />

      <PasswordField
        id="password"
        name="password"
        label={t("fields.password")}
        autoComplete="current-password"
        value={values.password}
        onChange={(event) => set("password", event.target.value)}
        error={errors.password}
        showLabel={t("fields.showPassword")}
        hideLabel={t("fields.hidePassword")}
        showName={t("fields.showPasswordName")}
        hideName={t("fields.hidePasswordName")}
      />

      <div className="flex flex-col items-start gap-2">
        <SubmitButton variant="primary" busy={busy === "login"}>
          {busy === "login" ? t("login.submitting") : t("login.submit")}
        </SubmitButton>
        <Button variant="link" busy={busy === "link"} onClick={emailLink}>
          {busy === "link" ? t("login.magicLinkSending") : t("login.magicLink")}
        </Button>
      </div>

      <p className="border-t border-line pt-6 text-ink">
        {t.rich("login.noAccount", {
          signup: (chunks) => (
            <Link href="/signup" className={textLinkClass}>
              {chunks}
            </Link>
          ),
        })}
      </p>
    </Form>
  );
}
