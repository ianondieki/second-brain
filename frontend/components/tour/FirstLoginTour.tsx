"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { useStrings } from "@/components/ClientStrings";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Illustration, type IllustrationKind } from "@/components/ui/Illustration";
import { focusPageTitle } from "@/lib/focus";

import { finishTour, rememberTourCookie, subscribeTour, tourCookieSet, tourDone, type TourSide } from "./tour-store";

export type { TourSide };

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
 * stays usable. It sits in the page's flow above the title at every width, so it covers nothing it points at and no
 * focused control, and it arrives with the page (tour-store.ts: a cookie the server reads, storage the client reads,
 * an inline script that hides a stale one before paint), so nothing shifts. Each step is a drawing, a title and one
 * sentence; "Skip tour", "Done" or Escape pressed inside it remembers it in this browser and hands focus back to the
 * page's title. Its forward button is a secondary button: the page keeps its one primary action.
 */
export function FirstLoginTour({ side, initialDone = true }: { side: TourSide; initialDone?: boolean }) {
  const t = useStrings("tour");
  // The server's answer comes from the cookie: the page arrives with the tour or without it, whole.
  const done = useSyncExternalStore(subscribeTour, () => tourDone(side), () => initialDone);
  const [index, setIndex] = useState(0);
  const titleId = useId();
  const bodyId = useId();
  const panel = useRef<HTMLElement>(null);

  // Storage remembers for as long as the person comes back, a cookie set from a page lapses sooner (Safari caps it at
  // seven days): when storage says done and the cookie is gone, write it again, so the next visit renders no tour.
  useEffect(() => {
    if (done && !tourCookieSet(side)) rememberTourCookie(side);
  }, [done, side]);

  // While open: Escape from inside it closes it (not an Escape meant for the account menu or a dialog).
  useEffect(() => {
    if (done) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Node && panel.current?.contains(event.target)) close(side);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [done, side]);

  if (done) return null;
  const steps = STEPS[side];
  const step = steps[index];
  const last = index === steps.length - 1;
  return (
    <section
      ref={panel}
      role="dialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      data-tour={step.key}
      data-tour-side={side}
      className="tour-enter mb-8 rounded-panel border border-line bg-field p-5 text-ink shadow-overlay sm:max-w-xl"
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
            <button type="button" onClick={() => close(side)} className={buttonClass("link", "shrink-0 whitespace-nowrap px-2")}>
              {t("skip")}
            </button>
          )}
          <button
            type="button"
            onClick={() => (last ? close(side) : setIndex(index + 1))}
            className={buttonClass("secondary", "min-h-11 w-auto shrink-0 whitespace-nowrap px-4")}
          >
            {last ? t("done") : t("next")}
          </button>
        </div>
      </div>
    </section>
  );
}

/** Skip, Done or Escape: remembered, then focus goes to the page's title rather than to <body>. */
function close(side: TourSide) {
  finishTour(side);
  focusPageTitle();
}
