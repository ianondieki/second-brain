"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { api } from "@/lib/api/client";

import { Button } from "./ui/Button";

/** Ends the session (POST /api/auth/logout), goes to the login page and drops the router's cached screens. */
export function SignOutButton() {
  const t = useTranslations("shell");
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await api.POST("/api/auth/logout");
    } catch {
      // Offline or already expired: the person asked to leave, so leave anyway.
    }
    router.replace("/login");
    router.refresh();
  }

  return (
    <Button variant="link" busy={busy} onClick={signOut}>
      {busy ? t("signingOut") : t("signOut")}
    </Button>
  );
}
