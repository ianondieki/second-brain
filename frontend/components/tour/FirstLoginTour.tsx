"use client";

import { useId, useState, useSyncExternalStore } from "react";

import { useStrings } from "@/components/ClientStrings";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Illustration, type IllustrationKind } from "@/components/ui/Illustration";

import { finishTour, subscribeTour, tourDone } from "./tour-store";

export type TourSide = "developer" | "org";

type StepKey = "devHome" | "devIdeas" | "devTracker" | "orgInbox" | "orgNda" | "orgTracker";

const STEPS: Record<TourSide, ReadonlyArray<{ key: StepKey; art: IllustrationKind }>> = {
  developer: [
    { key: "devHome", art: "empty" },
    { key: "devIdeas", art: "done" },
    { key: "devTracker", art: "waiting" },
  ],
  org: [
    { key: "orgInbox", art: "empty" },
    { key: "orgNda", art: "done" },
    { key: "orgTracker", art: "waiting" },
  ],
};

/**
 * The first-login tour (D-52; docs/spec/07: at most three steps, skippable from the first): a card that sits above
 * the tab bar on phones and bottom-right on desktop, never a modal (the page stays usable). Each step is a drawing, a
 * title and one sentence; "Skip tour" or "Done" remembers it in this browser (tour-store.ts). Its forward button is
 * styled as the primary action but carries no data-primary: the page keeps its own one.
 */
export function FirstLoginTour({ side }: { side: TourSide }) {
  const t = useStrings("tour");
  const done = useSyncExternalStore(subscribeTour, tourDone, () => true);
  const [index, setIndex] = useState(0);
  const titleId = useId();
  const bodyId = useId();
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
        "tour-enter fixed inset-x-3 z-20 rounded-panel border border-line bg-field p-5 text-ink shadow-overlay",
        "bottom-[calc(4rem+env(safe-area-inset-bottom))] sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-80 lg:bottom-8",
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
            <button type="button" onClick={finishTour} className={buttonClass("link", "whitespace-nowrap px-2")}>
              {t("skip")}
            </button>
          )}
          <button
            type="button"
            onClick={() => (last ? finishTour() : setIndex(index + 1))}
            className={buttonClass("primary", "min-h-11 w-auto whitespace-nowrap px-4")}
          >
            {last ? t("done") : t("next")}
          </button>
        </div>
      </div>
    </section>
  );
}
