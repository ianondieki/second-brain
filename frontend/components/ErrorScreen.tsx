"use client";

import { useStrings } from "./ClientStrings";

// Every route in a group downloads its error boundary, so this stays small: on purpose it keeps its own plain button
// with the primary button's look and tokens (components/ui/Button.tsx, bg-accent, hover --accent-strong) instead
// of importing the Button module (docs/platform/design/p16-design-system.md, Errors; the 150 KB budget).
const PRIMARY =
  "inline-flex min-h-12 w-full items-center justify-center rounded-control bg-accent px-6 text-base " +
  "font-semibold text-on-accent sm:w-auto hover:bg-accent-strong";

/**
 * A page that failed to render (error.tsx of a route group): a neutral sentence, since the cause is not known here
 * (API down, timeout, bug), and one way forward.
 */
export function ErrorScreen({ retry }: { retry: () => void }) {
  const t = useStrings("errorPage");
  return (
    <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 pt-16 pb-16 sm:px-6">
      <div className="max-w-md">
        <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
        <p className="mt-3 text-ink-soft">{t("body")}</p>
        <div className="mt-8">
          <button type="button" data-primary="" className={PRIMARY} onClick={() => retry()}>
            {t("retry")}
          </button>
        </div>
      </div>
    </main>
  );
}
