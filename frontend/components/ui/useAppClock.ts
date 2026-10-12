"use client";

import { useEffect, useState } from "react";

export const MINUTE = 60_000;
export const DAY = 1_440 * MINUTE;

// The app clock as this page keeps it: the browser's clock less a gap, taken from the first server instant a
// countdown was given (the API's X-App-Now) and moved only by an instant ahead of the clock's own reading. It lives as
// long as the page, so a screen drawn from the router's cache, prefetched earlier or restored from the back/forward
// cache, whose `now` is old (even if newer than the last one seen), never sets it back; a browser clock set wrong is
// absorbed by the gap; time asleep is counted, since the browser's clock runs on through it. One module, so every
// countdown on the page (Countdown, DeadlineClock) reads the same clock and none drifts from another.
let gap: number | null = null;

function appTime(served: number): number {
  if (gap === null || served > Date.now() - gap) gap = Date.now() - served;
  return Date.now() - gap;
}

/**
 * The milliseconds left to `end` on the app clock (P23-3, P26). The first render is the server's figure (`end` less
 * `served`), so hydration matches its HTML; the first tick then waits for the next minute boundary, unless the page's
 * instant is already a minute or more behind the app clock (a cached or restored page), when it is put right at once.
 * After that it ticks on each whole minute of what is left (one timeout chain), pauses while the tab is hidden, and is
 * recomputed when the tab is shown, the page is restored or the window regains focus; it stops at `end`.
 */
export function useTimeLeft(end: number, served: number): number {
  const [at, setAt] = useState(served);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Just past the next whole minute of what is left, where the floored figure changes.
    const schedule = (time: number) => {
      if (end > time) timer = setTimeout(run, ((end - time) % MINUTE) + 1);
    };
    function run() {
      clearTimeout(timer);
      if (document.hidden) return;
      const time = appTime(served);
      setAt(time);
      schedule(time);
    }
    const time = appTime(served);
    if (time - served >= MINUTE) timer = setTimeout(run, 0);
    else schedule(time);
    document.addEventListener("visibilitychange", run);
    addEventListener("pageshow", run);
    addEventListener("focus", run);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", run);
      removeEventListener("pageshow", run);
      removeEventListener("focus", run);
    };
  }, [end, served]);

  return end - Math.max(at, served);
}

/** Whole days, hours and minutes in a span of milliseconds (floored to the minute). */
export function splitLeft(left: number): { d: number; h: number; m: number } {
  const total = Math.floor(left / MINUTE);
  return {
    d: Math.floor(total / 1_440),
    h: Math.floor(total / 60) % 24,
    m: total % 60,
  };
}
