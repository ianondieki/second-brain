"use client";

import { useEffect, useState } from "react";

const MINUTE = 60_000;
const DAY = 1_440 * MINUTE;

export interface CountdownProps {
  /** The instant the window closes (ISO 8601). */
  until: string;
  /** The app clock's instant when the page was drawn (the API's X-App-Now), never the browser's clock. */
  now: string;
  /** Said instead of the time once `until` is reached ("Overdue", "Closed"). */
  labelWhenPast: string;
  /** "warm": the step is the viewer's, so under 24 hours the time takes the saffron "your turn" mark. */
  tone?: "neutral" | "warm";
  /** The figure from its largest unit down: `countdown.days`, `.hours`, `.minutes` with their {slots} left in. */
  units: readonly [string, string, string];
  /** The sentence around the figure, its {time} slot left in (`countdown.left`, `countdown.closesIn`). */
  frame: string;
  /** The full instant in words (Nairobi time), the <time>'s title. */
  title: string;
  className?: string;
}

/**
 * Time left to an instant in days, hours and minutes (P23-3). The basis is the server's instant plus the time this
 * page has been open (performance.now(), a monotonic clock), so a browser clock set wrong changes nothing. It
 * re-renders on each whole minute through one timeout chain, paused while the tab is hidden. No live region: a
 * ticking figure is never announced. Past `until` it says `labelWhenPast`.
 */
export function Countdown({ until, now, labelWhenPast, tone, units, frame, title, className }: CountdownProps) {
  const base = Date.parse(until) - Date.parse(now);
  // The time spent since this basis was drawn; a new basis (a refreshed page's X-App-Now) starts again from nothing.
  const [elapsed, setElapsed] = useState({ base, spent: 0 });

  useEffect(() => {
    const start = performance.now();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = (left: number) => {
      // Just past the next whole minute of what is left, where the floored figure changes.
      if (left > 0) timer = setTimeout(run, (left % MINUTE) + 1);
    };
    function run() {
      clearTimeout(timer);
      if (document.hidden) return;
      const spent = performance.now() - start;
      setElapsed({ base, spent });
      schedule(base - spent);
    }
    schedule(base);
    document.addEventListener("visibilitychange", run);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [base]);

  const left = base - (elapsed.base === base ? elapsed.spent : 0);
  const total = Math.floor(left / MINUTE);
  // Keyed by the first letter of each slot ({days}, {hours}, {minutes}).
  const parts: Record<string, number> = { d: Math.floor(total / 1_440), h: Math.floor(total / 60) % 24, m: total % 60 };
  const [before, after] = frame.split("{time}");
  // The look of each state ("warm": the saffron mark and the warm figure) is in the caller's className, keyed on
  // data-timer, so none of it ships in this bundle.
  return (
    <span data-timer={left > 0 ? (tone === "warm" && left < DAY ? "warm" : "open") : "past"} className={className}>
      {left > 0 ? (
        <>
          {before}
          <time dateTime={until} title={title} suppressHydrationWarning>
            {units[parts.d ? 0 : parts.h ? 1 : 2].replace(/\{(\w)\w*\}/g, (_, name: string) => String(parts[name]))}
          </time>
          {after}
        </>
      ) : (
        labelWhenPast
      )}
    </span>
  );
}
