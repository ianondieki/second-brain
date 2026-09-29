"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useStrings } from "./ClientStrings";

import { withCsrf } from "@/lib/api/csrf";
import { forgetEmail } from "@/lib/auth/remembered-email";

import { Button } from "./ui/Button";
import { AlertIcon } from "./ui/icons";

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
    // Only the CSRF helper, not the typed client: this button is on every signed-in page (the 150 KB JS budget).
    const status = await withCsrf()("/api/auth/logout", { method: "POST", credentials: "same-origin" }).then(
      (response) => response.status,
      () => 0, // offline or reset: may still be signed in
    );
    if (status === 204 || status === 401) {
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
