"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { Form, SubmitButton } from "@/components/ui/Form";
import { Alert } from "@/components/ui/Alert";
import { Button, ButtonLink, textLinkClass } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { destinationFor, LINK_MINUTES } from "@/lib/auth/routing";
import { continueAfterSignIn, rememberEmail } from "@/lib/auth/session";
import { checkEmail } from "@/lib/auth/validation";

/** A copy of a history state value with every occurrence of the token removed (the router may keep URLs there). */
export function scrubToken(value: unknown, token: string): unknown {
  if (typeof value === "string") return value.split(`#token=${token}`).join("").split(token).join("");
  if (Array.isArray(value)) return value.map((item) => scrubToken(item, token));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, scrubToken(item, token)]));
  }
  return value;
}

/**
 * Reads the token from the fragment (never sent to servers or in Referer), then removes it from the address bar, the
 * history entry and the Next.js router, so Back, bookmarks and shoulder-surfers do not see it and no later router
 * update (refresh, server action, dev reload) writes it back.
 */
export function takeTokenFromFragment(): string | null {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
  const clean = window.location.pathname + window.location.search;
  // At once: the address bar and the history entry (Next's own state is kept, minus the token).
  const state = token ? scrubToken(window.history.state, token) : window.history.state;
  window.history.replaceState(state, "", clean);
  // The router keeps its own copy of the URL. Next syncs it on a replaceState that is not its own (no `__NA` in the
  // state), but installs that hook in an effect of the app router, which runs after this component's effects on
  // first load. So repeat the replace once effects have settled, the way Next documents (state null, new path).
  window.setTimeout(() => {
    if (window.location.pathname + window.location.search === clean && !window.location.hash) {
      window.history.replaceState(null, "", clean);
    }
  }, 0);
  return token;
}

/** Failures that say nothing about the link itself: keep the token and offer to try again. */
const RETRYABLE = new Set<ErrorKey>(["network", "csrf_failed"]);

/**
 * Magic and verification links land here: `/auth/link#token=...`. The token is spent once (POST
 * /api/auth/magic-link/consume); a used or expired link offers a new one on the spot.
 */
export function LinkSignIn() {
  const t = useTranslations();
  const router = useRouter();
  const started = useRef(false);
  const token = useRef<string | null>(null);
  const [failed, setFailed] = useState<ErrorKey | null>(null);
  const [interrupted, setInterrupted] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [noPassword, setNoPassword] = useState(false);
  const [home, setHome] = useState("/dev");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<ErrorKey | null>(null);

  const signIn = useCallback(async () => {
    // Taken from the address bar once; kept in memory so "Try again" can use it after a dropped connection.
    token.current ??= takeTokenFromFragment();
    const current = token.current;
    if (!current) {
      setFailed("invalid_or_expired_link");
      return;
    }
    const outcome = await settle(api.POST("/api/auth/magic-link/consume", { body: { token: current } }));
    setRetrying(false);
    if (outcome.ok) {
      token.current = null;
      // Signed in, but the account has no password (for example: the link was opened in a different browser from
      // the one that signed up, so the password chosen there was not kept). Say so calmly, with one way forward.
      if (!outcome.data.mfa_required && !outcome.data.user.password_set) {
        const me = await settle(api.GET("/api/auth/me"));
        if (me.ok) setHome(destinationFor(me.data));
        setNoPassword(true);
        return;
      }
      await continueAfterSignIn(router, outcome.data.mfa_required);
      return;
    }
    if (RETRYABLE.has(outcome.key)) {
      setInterrupted(true);
      return;
    }
    token.current = null;
    // A validation error (malformed token) means the same thing to the person as an expired link.
    setFailed(outcome.key === "validation" ? "invalid_or_expired_link" : outcome.key);
  }, [router]);

  async function tryAgain() {
    setRetrying(true);
    await signIn();
  }

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

  if (noPassword) {
    return (
      <>
        <h1 className="text-xl text-ink lg:text-2xl">{t("link.noPasswordTitle")}</h1>
        <p className="mt-3 text-ink-soft">{t("link.noPasswordBody")}</p>
        <div className="mt-8 flex flex-col items-start gap-4">
          <ButtonLink href="/settings/security#password" variant="primary">
            {t("link.noPasswordAction")}
          </ButtonLink>
          <Link href={home} className={textLinkClass}>
            {t("link.noPasswordLater")}
          </Link>
        </div>
      </>
    );
  }

  if (interrupted) {
    return (
      <>
        <h1 className="text-xl text-ink lg:text-2xl">{t("link.interruptedTitle")}</h1>
        <p role="status" className="mt-3 text-ink-soft">
          {t("link.interruptedBody")}
        </p>
        <div className="mt-8">
          <Button variant="primary" busy={retrying} onClick={tryAgain}>
            {retrying ? t("link.working") : t("link.tryAgain")}
          </Button>
        </div>
      </>
    );
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
      <Form onSubmit={requestNewLink} className="mt-8 flex flex-col gap-6">
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
          <SubmitButton variant="primary" busy={sending}>
            {sending ? t("link.submitting") : t("link.submit")}
          </SubmitButton>
        </div>
      </Form>
    </>
  );
}
