"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { rememberEmail } from "@/lib/auth/session";

/**
 * For `recent_sign_in_required`: an account without a password proves it is the owner by signing in again with an
 * emailed link (the API then allows credential changes for 15 minutes).
 */
export function SignInAgain({ email }: { email: string }) {
  const t = useTranslations("security");
  const te = useTranslations("errors");
  const router = useRouter();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ErrorKey | null>(null);

  async function send() {
    setSending(true);
    setError(null);
    const outcome = await settle(api.POST("/api/auth/magic-link", { body: { email } }));
    if (outcome.ok) {
      rememberEmail(email);
      router.push("/signup/check-email?for=login");
      return;
    }
    setSending(false);
    setError(outcome.key);
  }

  return (
    <div className="flex flex-col items-start gap-3">
      {error ? <Alert>{te(error)}</Alert> : null}
      <Button variant="secondary" busy={sending} onClick={send}>
        {sending ? t("emailLinkSending") : t("emailLink")}
      </Button>
    </div>
  );
}
