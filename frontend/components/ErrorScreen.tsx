"use client";

import { useTranslations } from "next-intl";

import { Button } from "./ui/Button";

/**
 * A page that failed to render (error.tsx of a route group): a neutral sentence, since the cause is not known here
 * (API down, timeout, bug), and one way forward.
 */
export function ErrorScreen({ retry }: { retry: () => void }) {
  const t = useTranslations("errorPage");
  return (
    <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 pt-16 pb-16 sm:px-6">
      <div className="max-w-md">
        <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
        <p className="mt-3 text-ink-soft">{t("body")}</p>
        <div className="mt-8">
          <Button variant="primary" onClick={() => retry()}>
            {t("retry")}
          </Button>
        </div>
      </div>
    </main>
  );
}
