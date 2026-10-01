"use client";

import { useEffect, useId, useState, useSyncExternalStore } from "react";

import { useStrings } from "@/components/ClientStrings";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Illustration, type IllustrationKind } from "@/components/ui/Illustration";
import { focusPageTitle } from "@/lib/focus";

import { finishTour, subscribeTour, tourDone } from "./tour-store";

export type TourSide = "developer" | "org";

type StepKey = "devHome" | "devIdeas" | "devTracker" | "orgInbox" | "orgNda" | "orgTracker";

const STEPS: Record<TourSide, ReadonlyArray<{ key: StepKey; art: IllustrationKind }>> = {
  developer: [
    { key: "devHome", art: "guide" },
    { key: "devIdeas", art: "done" },
    { key: "devTracker", art: "waiting" },
  ],
  org: [
    { key: "orgInbox", art: "guide" },
    { key: "orgNda", art: "done" },
    { key: "orgTracker", art: "waiting" },
  ],
};

/**
 * The first-login tour (D-52; docs/spec/07: at most three steps, skippable from the first), never a modal: the page
 * stays usable. On phones it sits in the page's flow above the title, so it covers nothing it points at and no focused
 * control; from 640 px it floats bottom-right, and the page keeps that much room at its end (globals.css,
 * `html[data-tour-open]`) so a focused control can always scroll clear of it. Each step is a drawing, a title and one
 * sentence; "Skip tour", "Done" or Escape remembers it in this browser (tour-store.ts) and hands focus back to the
 * page's title. Its forward button is styled as the primary action but carries no data-primary: the page keeps its own.
 */
export function FirstLoginTour({ side }: { side: TourSide }) {
  const t = useStrings("tour");
  const done = useSyncExternalStore(subscribeTour, tourDone, () => true);
  const [index, setIndex] = useState(0);
  const titleId = useId();
  const bodyId = useId();

  // While open: Escape closes it, and the document reserves its room at the page's end from 640 px.
  useEffect(() => {
    if (done) return;
    const root = document.documentElement;
    root.setAttribute("data-tour-open", "");
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) close();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      root.removeAttribute("data-tour-open");
      document.removeEventListener("keydown", onKey);
    };
  }, [done]);

  if (done) return null;
  const steps = STEPS[side];
  const step = steps[index];
  const last = index === steps.length - 1;
  return (
    <section
      role="dialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      data-tour={step.key}
      className={cn(
        "tour-enter z-20 rounded-panel border border-line bg-field p-5 text-ink shadow-overlay",
        "mb-8 sm:fixed sm:right-6 sm:bottom-6 sm:mb-0 sm:w-80 lg:bottom-8",
      )}
    >
      <Illustration kind={step.art} className="max-w-40 text-ink" />
      <p className="mt-3 text-xs font-medium text-ink-soft tabular-nums">{t("stepOf", { current: index + 1, total: steps.length })}</p>
      <h2 id={titleId} className="mt-1 text-lg text-ink">
        {t(`${step.key}.title`)}
      </h2>
      <p id={bodyId} className="mt-1.5 text-sm text-ink-soft">
        {t(`${step.key}.body`)}
      </p>
      <div className="mt-4 flex items-center justify-between gap-3">
        <ol aria-hidden="true" className="flex gap-1.5">
          {steps.map((s, i) => (
            <li key={s.key} className={cn("h-1.5 w-4 rounded-full", i <= index ? "bg-accent" : "bg-line")} />
          ))}
        </ol>
        <div className="flex items-center gap-2">
          {last ? null : (
            <button type="button" onClick={close} className={buttonClass("link", "whitespace-nowrap px-2")}>
              {t("skip")}
            </button>
          )}
          <button
            type="button"
            onClick={() => (last ? close() : setIndex(index + 1))}
            className={buttonClass("primary", "min-h-11 w-auto whitespace-nowrap px-4")}
          >
            {last ? t("done") : t("next")}
          </button>
        </div>
      </div>
    </section>
  );
}

/** Skip, Done or Escape: remembered, then focus goes to the page's title rather than to <body>. */
function close() {
  finishTour();
  focusPageTitle();
}
