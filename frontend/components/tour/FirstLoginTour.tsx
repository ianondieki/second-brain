"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { useStrings } from "@/components/ClientStrings";
import { buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { Illustration, type IllustrationKind } from "@/components/ui/Illustration";
import { focusPageTitle } from "@/lib/focus";

import { finishTour, rememberTourCookie, subscribeTour, tourCookieSet, tourDone } from "./tour-store";

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
 * control; from 640 px it floats bottom-right above the tab bar, and the page keeps that much room at its end
 * (globals.css, `html[data-tour-open]`) so a focused control can always scroll clear of it. Each step is a drawing, a
 * title and one sentence; "Skip tour", "Done" or Escape pressed inside it remembers it in this browser (tour-store.ts:
 * in storage and in a cookie the server reads, so the page arrives with or without the tour and never shifts) and
 * hands focus back to the page's title. Its forward button is styled as the primary action but carries no
 * data-primary: the page keeps its own.
 */
export function FirstLoginTour({ side, initialDone = true }: { side: TourSide; initialDone?: boolean }) {
  const t = useStrings("tour");
  // The server's answer comes from the cookie (tour-store.ts): the page arrives with the tour or without it, whole.
  const done = useSyncExternalStore(subscribeTour, tourDone, () => initialDone);
  const [index, setIndex] = useState(0);
  const titleId = useId();
  const bodyId = useId();
  const panel = useRef<HTMLElement>(null);

  // Storage remembers for as long as the person comes back, a cookie set from a page lapses sooner (Safari caps it at
  // seven days): when storage says done and the cookie is gone, write it again, so the next visit renders no tour.
  useEffect(() => {
    if (done && !tourCookieSet()) rememberTourCookie();
  }, [done]);

  // While open: Escape from inside it closes it (not an Escape meant for the account menu or a dialog), and the
  // document reserves its room at the page's end from 640 px.
  useEffect(() => {
    if (done) return;
    const root = document.documentElement;
    root.setAttribute("data-tour-open", "");
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Node && panel.current?.contains(event.target)) close();
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
      ref={panel}
      role="dialog"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      data-tour={step.key}
      className={cn(
        "tour-enter z-20 rounded-panel border border-line bg-field p-5 text-ink shadow-overlay",
        // Above the fixed tab bar until the rail takes over at 1024 px.
        "mb-8 sm:fixed sm:right-6 sm:bottom-[calc(4.5rem+env(safe-area-inset-bottom))] sm:mb-0 sm:w-80 lg:bottom-8",
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
