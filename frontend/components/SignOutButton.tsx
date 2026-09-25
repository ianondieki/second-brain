"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { api } from "@/lib/api/client";

import { Button } from "./ui/Button";

/** Ends the session (POST /api/auth/logout) and starts fresh on the login page, dropping any cached screens. */
export function SignOutButton() {
  const t = useTranslations("shell");
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await api.POST("/api/auth/logout");
    } finally {
      // Whatever the answer, the person asked to leave: the server session is gone or already expired.
      window.location.assign("/login");
    }
  }

  return (
    <Button variant="link" busy={busy} onClick={signOut}>
      {busy ? t("signingOut") : t("signOut")}
    </Button>
  );
}
