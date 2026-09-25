"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense, type Ref } from "react";

import { Alert } from "@/components/ui/Alert";
import { textLinkClass } from "@/components/ui/Button";
import type { ErrorKey } from "@/lib/api/errors";

import { SignInAgain } from "./lazy";

/**
 * An API error on the security page, with the one way forward where there is one: a fresh sign-in link for
 * recent_sign_in_required (accounts without a password), the login page when the session has ended.
 */
export function ErrorNotice({
  error,
  email,
  alertRef,
}: {
  error: ErrorKey | null;
  email?: string;
  alertRef?: Ref<HTMLDivElement>;
}) {
  const t = useTranslations("security");
  const te = useTranslations("errors");
  if (!error) return null;
  return (
    <>
      <Alert ref={alertRef}>{te(error)}</Alert>
      {error === "recent_sign_in_required" && email ? (
        <Suspense fallback={null}>
          <SignInAgain email={email} />
        </Suspense>
      ) : null}
      {error === "unauthenticated" ? (
        <Link href="/login" className={textLinkClass}>
          {t("logInAgain")}
        </Link>
      ) : null}
    </>
  );
}
