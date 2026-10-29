"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { ArrowLeftIcon, ArrowRightIcon, PauseIcon, PlayIcon } from "@/components/icons/lucide";
import { buttonClass } from "@/components/ui/Button";
import { focusPageTitle } from "@/lib/focus";

import { finishTour, rememberTourCookie, subscribeTour, tourCookieSet, tourDone, type TourSide } from "./tour-store";

export type { TourSide };

type StepKey = "devHome" | "devIdeas" | "devTracker" | "orgInbox" | "orgNda" | "orgTracker";

const STEPS: Record<TourSide, readonly StepKey[]> = {
  developer: ["devHome", "devIdeas", "devTracker"],
  org: ["orgInbox", "orgNda", "orgTracker"],
};

/** How long a step stays before the next one slides in (globals.css `.tour-seg` fills over the same time). */
export const TOUR_DWELL_MS = 6000;
/** A swipe moves a step once the finger has travelled this far sideways. */
const SWIPE_PX = 40;
// Why the slide show is holding still (a bit each): the pointer is over it, focus is in it, a finger is on it, the
// tab is hidden. The person's own Pause is apart (`paused`).
const HOVER = 1;
const FOCUS = 2;
const TOUCH = 4;
const HIDDEN = 8;

/** The time now, read only inside effects and their cleanups (the dwell clock). */
const now = () => Date.now();

const REDUCE = "(prefers-reduced-motion: reduce)";
function subscribeMotion(change: () => void) {
  const query = typeof matchMedia === "function" ? matchMedia(REDUCE) : null;
  query?.addEventListener("change", change);
  return () => query?.removeEventListener("change", change);
}
const reducedMotion = () => typeof matchMedia === "function" && matchMedia(REDUCE).matches;

/**
 * The first-login tour (D-52; docs/spec/07: at most three steps, skippable from the first), never a modal: the page
 * stays usable. It sits in the page's flow above the title at every width, so it covers nothing it points at and no
 * focused control, and it arrives with the page (tour-store.ts: a cookie the server reads, storage the client reads,
 * an inline script that hides a stale one before paint), so nothing shifts.
 *
 * P23-2: a slide show. Each step is a scene (TourScenes.tsx, rendered on the server and passed in), a title and one
 * sentence; the steps slide sideways every six seconds along a thin progress line, and hold still while the panel is
 * hovered, has focus or a finger on it, or the tab is hidden; the last step stays. Back, Next, the steps' own buttons,
 * Pause (WCAG 2.2.2), a swipe and the arrow keys move it; a polite live region says which step is showing, and
 * advancing never moves focus. Reduced motion: no advancing, a crossfade, no Pause. All steps share one grid cell, so
 * the panel is as tall as its tallest step and the page under it never moves. "Skip tour", "Done" or Escape inside it
 * remember it and hand focus to the page's title. Its buttons are secondary: the page keeps its one primary action.
 */
export function FirstLoginTour({ side, initialDone = true, scenes }: { side: TourSide; initialDone?: boolean; scenes?: ReactNode[] }) {
  const t = useStrings("tour");
  // The server's answer comes from the cookie: the page arrives with the tour or without it, whole.
  const done = useSyncExternalStore(subscribeTour, () => tourDone(side), () => initialDone);
  const reduce = useSyncExternalStore(subscribeMotion, reducedMotion, () => false);
  const [index, setIndex] = useState(0);
  const [from, setFrom] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);
  const [holds, setHolds] = useState(0);
  const id = useId();
  const panel = useRef<HTMLElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const pause = useRef<HTMLButtonElement>(null);
  const swipe = useRef<number | null>(null);
  const refocus = useRef(false);
  const clock = useRef({ step: 0, left: TOUR_DWELL_MS });

  const steps = STEPS[side];
  const last = steps.length - 1;
  const running = !done && !reduce && !paused && holds === 0 && index < last;
  const hold = (bit: number, on: boolean) => setHolds((h) => (on ? h | bit : h & ~bit));

  function go(n: number) {
    if (n < 0 || n > last || n === index) return;
    // A control that leaves with the step (Back on the first, Skip on the last) hands its focus to Next, not <body>.
    refocus.current = !!panel.current?.contains(document.activeElement);
    // The step starts its six seconds again, as its progress line does.
    clock.current = { step: n, left: TOUR_DWELL_MS };
    setFrom(index);
    setIndex(n);
  }

  // Storage remembers for as long as the person comes back, a cookie set from a page lapses sooner (Safari caps it at
  // seven days): when storage says done and the cookie is gone, write it again, so the next visit renders no tour.
  useEffect(() => {
    if (done && !tourCookieSet(side)) rememberTourCookie(side);
  }, [done, side]);

  // While open: Escape from inside it closes it (not an Escape meant for the account menu or a dialog); a hidden tab holds it.
  useEffect(() => {
    if (done) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Node && panel.current?.contains(event.target)) close(side);
    };
    const onVisibility = () => hold(HIDDEN, document.visibilityState === "hidden");
    onVisibility();
    document.addEventListener("keydown", onKey);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [done, side]);

  // The six seconds: a hold keeps what is left of them, a new step starts them again.
  useEffect(() => {
    if (!running) return;
    if (clock.current.step !== index) clock.current = { step: index, left: TOUR_DWELL_MS };
    const started = now();
    const timer = setTimeout(() => {
      setFrom(index);
      setIndex(index + 1);
    }, clock.current.left);
    return () => {
      clearTimeout(timer);
      if (clock.current.step === index) clock.current.left -= now() - started;
    };
  }, [running, index]);

  // Focus never falls to <body>: a control that left with the step, or Pause, which the last step hides (it may be
  // focused when the last step arrives, by Play or by an arrow key), hands focus to Next (Done there).
  useEffect(() => {
    const active = document.activeElement;
    const gone = refocus.current && !panel.current?.contains(active);
    if (gone || (index === last && active === pause.current)) next.current?.focus();
    refocus.current = false;
  }, [index, last]);

  if (done) return null;
  const key = steps[index];
  return (
    <section
      ref={panel}
      role="dialog"
      aria-labelledby={`${id}t${index}`}
      aria-describedby={`${id}b${index}`}
      data-tour={key}
      data-tour-side={side}
      data-held={running ? undefined : ""}
      className={reduce ? "tour tour-enter tour-fade" : "tour tour-enter"}
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") hold(HOVER, true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") hold(HOVER, false);
      }}
      onPointerDown={(e) => {
        if (e.pointerType === "mouse") return;
        swipe.current = e.clientX;
        hold(TOUCH, true);
      }}
      onPointerUp={(e) => {
        const dx = swipe.current === null ? 0 : e.clientX - swipe.current;
        swipe.current = null;
        hold(TOUCH, false);
        if (Math.abs(dx) >= SWIPE_PX) go(index + (dx < 0 ? 1 : -1));
      }}
      onPointerCancel={() => {
        swipe.current = null;
        hold(TOUCH, false);
      }}
      onFocus={(e) => {
        // Keyboard focus holds the slide show; a mouse click that focuses a button does not (it would stop it for good).
        if (e.target.matches(":focus-visible")) hold(FOCUS, true);
      }}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) hold(FOCUS, false);
      }}
      onKeyDown={(e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        e.preventDefault();
        go(index + step);
      }}
    >
      <div className="tour-head">
        {steps.map((s, i) => (
          <button
            key={s}
            type="button"
            className="tour-seg"
            aria-label={t("step", { number: i + 1 })}
            aria-current={i === index ? "step" : undefined}
            data-done={i < index ? "" : undefined}
            onClick={() => go(i)}
          >
            <i />
          </button>
        ))}
        {reduce ? null : (
          <button
            ref={pause}
            type="button"
            className={index === last ? "tour-pause invisible" : "tour-pause"}
            aria-label={t("pause")}
            aria-pressed={paused}
            title={t("pause")}
            onClick={() => {
              // Play overrides the hover and focus that come with pressing it; a hidden tab still holds.
              if (paused) setHolds((h) => h & HIDDEN);
              setPaused(!paused);
            }}
          >
            {paused ? <PlayIcon /> : <PauseIcon />}
          </button>
        )}
      </div>
      <div className="tour-slides" data-back={from !== null && from > index ? "" : undefined}>
        {steps.map((s, i) => {
          const here = i === index;
          return (
            <div
              key={s}
              className="tour-slide"
              data-slide={here ? (from === null ? "on" : "in") : i === from ? "out" : undefined}
              aria-hidden={here ? undefined : true}
              inert={!here}
            >
              {scenes?.[i]}
              <div>
                <p aria-hidden="true" className="text-xs font-medium text-ink-soft tabular-nums">
                  {t("stepOf", { current: i + 1, total: steps.length })}
                </p>
                <h2 id={`${id}t${i}`} className="mt-1 text-lg text-ink">
                  {t(`${s}.title`)}
                </h2>
                <p id={`${id}b${i}`} className="mt-1.5 text-sm text-ink-soft">
                  {t(`${s}.body`)}
                </p>
              </div>
            </div>
          );
        })}
      </div>
      <p className="sr-only" aria-live="polite">
        {t("stepLabel", { current: index + 1, total: steps.length, title: t(`${key}.title`) })}
      </p>
      <div className="tour-foot">
        {index === last ? null : (
          <button type="button" onClick={() => close(side)} className={buttonClass("link", "mr-auto px-2")}>
            {t("skip")}
          </button>
        )}
        {index > 0 ? (
          <button type="button" onClick={() => go(index - 1)} className={buttonClass("secondary", "w-12 px-0")} aria-label={t("back")}>
            <ArrowLeftIcon className="size-5" />
          </button>
        ) : null}
        <button
          ref={next}
          type="button"
          onClick={() => (index === last ? close(side) : go(index + 1))}
          className={buttonClass("secondary", "px-5")}
        >
          {index === last ? t("done") : t("next")}
          {index === last ? null : <ArrowRightIcon className="size-5" />}
        </button>
      </div>
    </section>
  );
}

/** Skip, Done or Escape: remembered, then focus goes to the page's title rather than to <body>. */
function close(side: TourSide) {
  finishTour(side);
  focusPageTitle();
}
