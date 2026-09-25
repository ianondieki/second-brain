"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { LINK_MINUTES } from "@/lib/auth/routing";
import { continueAfterSignIn, rememberEmail } from "@/lib/auth/session";
import { checkEmail } from "@/lib/auth/validation";

/** Reads the token from the fragment (never sent to servers or in Referer), then forgets it. */
function takeTokenFromFragment(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
  window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  return token;
}

/**
 * Magic and verification links land here: `/auth/link#token=...`. The token is spent once (POST
 * /api/auth/magic-link/consume); a used or expired link offers a new one on the spot.
 */
export function LinkSignIn() {
  const t = useTranslations();
  const router = useRouter();
  const started = useRef(false);
  const [failed, setFailed] = useState<ErrorKey | null>(null);
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<ErrorKey | null>(null);

  const signIn = useCallback(async () => {
    const token = takeTokenFromFragment();
    if (!token) {
      setFailed("invalid_or_expired_link");
      return;
    }
    const outcome = await settle(api.POST("/api/auth/magic-link/consume", { body: { token } }));
    if (outcome.ok) {
      await continueAfterSignIn(router, outcome.data.mfa_required);
      return;
    }
    // A validation error (malformed token) means the same thing to the person as an expired link.
    setFailed(outcome.key === "generic" && outcome.status === 422 ? "invalid_or_expired_link" : outcome.key);
  }, [router]);

  useEffect(() => {
    // Once per page load, even under React's development double-invocation: a token only works once.
    if (started.current) return;
    started.current = true;
    void signIn();
  }, [signIn]);

  async function requestNewLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending) return;
    const invalid = checkEmail(email, "emailForLink");
    setEmailError(invalid && t(`validation.${invalid}`));
    if (invalid) {
      document.getElementById("email")?.focus();
      return;
    }
    setSending(true);
    setSendError(null);
    const outcome = await settle(api.POST("/api/auth/magic-link", { body: { email: email.trim() } }));
    if (outcome.ok) {
      rememberEmail(email);
      router.push("/signup/check-email?for=login");
      return;
    }
    setSending(false);
    setSendError(outcome.key);
  }

  if (!failed) {
    return (
      <>
        <h1 className="text-xl text-ink lg:text-2xl">{t("link.title")}</h1>
        <p role="status" className="mt-3 text-ink-soft">
          {t("link.working")}
        </p>
      </>
    );
  }

  return (
    <>
      <h1 className="text-xl text-ink lg:text-2xl">{t("link.failedTitle")}</h1>
      <p className="mt-3 text-ink-soft">
        {failed === "invalid_or_expired_link"
          ? t("link.failedLead", { minutes: LINK_MINUTES })
          : t(`errors.${failed}`)}
      </p>
      <form noValidate onSubmit={requestNewLink} className="mt-8 flex flex-col gap-6">
        {sendError ? <Alert>{t(`errors.${sendError}`)}</Alert> : null}
        <TextField
          id="email"
          name="email"
          type="email"
          label={t("fields.email")}
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setEmailError(undefined);
          }}
          error={emailError}
        />
        <div>
          <Button type="submit" variant="primary" busy={sending}>
            {sending ? t("link.submitting") : t("link.submit")}
          </Button>
        </div>
      </form>
    </>
  );
}
