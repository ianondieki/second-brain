"use client";

import { DAY, splitLeft, useTimeLeft } from "./useAppClock";

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
 * Time left to an instant in days, hours and minutes as a sentence (P23-3), ticking on the app clock (useAppClock.ts:
 * the server's figure first, then each whole minute, paused while the tab is hidden). No live region: a ticking figure
 * is never announced. Past `until` it says `labelWhenPast`. The look of each state is the caller's className, keyed on
 * data-timer.
 */
export function Countdown({ until, now, labelWhenPast, tone, units, frame, title, className }: CountdownProps) {
  const end = Date.parse(until);
  const served = Date.parse(now);
  // The app clock's scheduling is shared with DeadlineClock (useAppClock.ts): one clock per page.
  const left = useTimeLeft(end, served);
  const { d, h, m } = splitLeft(left);
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
