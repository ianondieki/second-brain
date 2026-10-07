"use client";

import { useEffect, useState } from "react";

const MINUTE = 60_000;
const DAY = 1_440 * MINUTE;

// The app clock as this page keeps it: the browser's clock less a gap, taken from the first server instant a
// countdown was given (the API's X-App-Now) and moved only by an instant ahead of the clock's own reading. It lives as
// long as the page, so a screen drawn from the router's cache, prefetched earlier or restored from the back/forward
// cache, whose `now` is old (even if newer than the last one seen), never sets it back; a browser clock set wrong is
// absorbed by the gap; time asleep is counted, since the browser's clock runs on through it.
let gap: number | null = null;

function appTime(served: number): number {
  if (gap === null || served > Date.now() - gap) gap = Date.now() - served;
  return Date.now() - gap;
}

export interface CountdownProps {
  /** The instant the window closes (ISO 8601). */
  until: string;
  /** The app clock's instant when the page was drawn (the API's X-App-Now). */
  now: string;
  /** Said instead of the time once `until` is reached ("Overdue", "Closed"). */
  labelWhenPast: string;
  /** "warm": the step is the viewer's, so under 24 hours the time takes the saffron "your turn" look. */
  tone?: "neutral" | "warm";
  /**
   * The figure from its largest unit down, with {hours} and {minutes} slots: one day, more days (its number written as
   * 99, put right here: a plural form chosen by the server's messages), hours, minutes.
   */
  units: readonly [string, string, string, string];
  /** The sentence around the figure, its {time} slot left in (`countdown.in`, `.dueIn`, `.closesIn`). */
  frame: string;
  /** The full instant in words (Nairobi time), the <time>'s title. */
  title: string;
  className?: string;
}

/**
 * Time left to an instant in days, hours and minutes (P23-3). The first render is the server's figure, so hydration
 * matches its HTML; the first tick then waits for the next minute boundary, unless the page's instant is already a
 * minute or more behind the app clock (a cached or restored page), when it is put right at once. After that it ticks
 * on each whole minute (one timeout chain), pauses while the tab is hidden, and is recomputed when the tab is shown,
 * the page is restored or the window regains focus. No live region: a ticking figure is never announced. Past `until`
 * it says `labelWhenPast`. The look of each state is the caller's className, keyed on data-timer.
 */
export function Countdown({ until, now, labelWhenPast, tone, units, frame, title, className }: CountdownProps) {
  const end = Date.parse(until);
  const served = Date.parse(now);
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

  const left = end - Math.max(at, served);
  const total = Math.floor(left / MINUTE);
  const d = Math.floor(total / 1_440);
  const h = Math.floor(total / 60) % 24;
  const m = total % 60;
  const [before, after] = frame.split("{time}");
  return (
    <span data-timer={left > 0 ? (tone === "warm" && left < DAY ? "warm" : "open") : "past"} className={className}>
      {left > 0 ? (
        <>
          {before}
          <time dateTime={`P${d}DT${h}H${m}M`} title={title} suppressHydrationWarning>
            {(d ? units[d > 1 ? 1 : 0].replace("99", String(d)) : units[h ? 2 : 3])
              .replace("{hours}", String(h))
              .replace("{minutes}", String(m))}
          </time>
          {after}
        </>
      ) : (
        labelWhenPast
      )}
    </span>
  );
}
