"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button, textLinkClass } from "@/components/ui/Button";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import type { ErrorKey } from "@/lib/api/errors";
import { LINK_MINUTES } from "@/lib/auth/routing";
import { useRememberedEmail } from "@/lib/auth/session";

export type CheckEmailKind = "signup" | "login";

/** One sentence and one action: send the same kind of link again to the address we just used. */
export function CheckEmail({ kind }: { kind: CheckEmailKind }) {
  const t = useTranslations("checkEmail");
  const tErrors = useTranslations("errors");
  const email = useRememberedEmail();
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<ErrorKey | null>(null);

  async function resend() {
    if (!email) return;
    setState("sending");
    setError(null);
    const body = { email };
    const outcome = await settle(
      kind === "login"
        ? api.POST("/api/auth/magic-link", { body })
        : api.POST("/api/auth/verify-email/resend", { body }),
    );
    if (outcome.ok) {
      setState("sent");
    } else {
      setState("idle");
      setError(outcome.key);
    }
  }

  const bold = (chunks: ReactNode) => <b className="font-semibold text-ink [overflow-wrap:anywhere]">{chunks}</b>;

  return (
    <>
      <p className="mt-3 text-ink-soft">
        {email
          ? t.rich(kind, { email, minutes: LINK_MINUTES, b: bold })
          : t("noEmail", { minutes: LINK_MINUTES })}
      </p>
      <div className="mt-8 flex flex-col items-start gap-4">
        {state === "sent" ? <Alert tone="ok">{t("resent")}</Alert> : null}
        {error ? <Alert>{tErrors(error)}</Alert> : null}
        {email ? (
          <Button variant="secondary" busy={state === "sending"} onClick={resend}>
            {state === "sending" ? t("resending") : t("resend")}
          </Button>
        ) : (
          <Link href="/login" className={textLinkClass}>
            {t("backToLogin")}
          </Link>
        )}
      </div>
    </>
  );
}
