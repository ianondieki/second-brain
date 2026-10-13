"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useStrings } from "./ClientStrings";

import { endSession } from "@/lib/auth/sign-out";

import { Button } from "./ui/Button";
import { AlertIcon } from "./ui/status-icons";

/**
 * Ends the session (POST /api/auth/logout). Only 204 (ended) or 401 (already gone) count as signed out; anything
 * else, including a network failure, keeps the person here with a warning that they may still be signed in.
 */
export function SignOutButton() {
  const t = useStrings("shell");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function signOut() {
    setBusy(true);
    setFailed(false);
    // Offline copies first, then the session, then this device's remembered address and recent pages (lib/auth/sign-out).
    if (await endSession()) {
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
        <p
          role="alert"
          className="mb-2 flex max-w-[18rem] items-start gap-1.5 text-right text-sm font-medium text-error"
        >
          <AlertIcon className="mt-px size-5 shrink-0" />
          <span>{t("signOutFailed")}</span>
        </p>
      ) : null}
    </div>
  );
}
