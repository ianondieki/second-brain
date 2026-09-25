"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";
import { forgetEmail } from "@/lib/auth/session";

import { Button } from "./ui/Button";
import { AlertIcon } from "./ui/icons";

/**
 * Ends the session (POST /api/auth/logout). Only 204 (ended) or 401 (already gone) count as signed out; anything
 * else, including a network failure, keeps the person here with a warning that they may still be signed in.
 */
export function SignOutButton() {
  const t = useTranslations("shell");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function signOut() {
    setBusy(true);
    setFailed(false);
    const outcome = await settle(api.POST("/api/auth/logout"));
    if (outcome.ok || outcome.status === 401) {
      forgetEmail(); // the next person on this device should not see this address offered back
      router.replace("/login");
      router.refresh();
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  return (
    <div className="flex flex-col items-end">
      <Button variant="link" busy={busy} onClick={signOut}>
        {busy ? t("signingOut") : failed ? t("signOutRetry") : t("signOut")}
      </Button>
      {failed ? (
        <p role="alert" className="mb-2 flex max-w-[18rem] items-start gap-1.5 text-right text-sm font-medium text-error">
          <AlertIcon className="mt-px size-5 shrink-0" />
          <span>{t("signOutFailed")}</span>
        </p>
      ) : null}
    </div>
  );
}
