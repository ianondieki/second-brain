"use client";

import { DAY, splitLeft, useTimeLeft } from "./useAppClock";

export interface ClockFiguresProps {
  /** The instant the window closes (the API's `due_at`). */
  until: string;
  /** The app clock's instant when the page was drawn (the API's X-App-Now). */
  now: string;
  /** Said instead of the figures once `until` is reached (the screen's own word, "Overdue"). */
  labelWhenPast: string;
  /** "warm": the step is the viewer's, so under 24 hours the figures take the saffron "your turn" look. */
  tone?: "neutral" | "warm";
  /**
   * The clock's messages as written, from its largest unit down: days, hours, minutes. Each tags a figure as
   * <f>{days}</f> (or {hours}, {minutes}) and a unit word as <u>…</u>; the text between groups is the language's own.
   */
  formats: readonly [string, string, string];
  /** The full instant in words (Nairobi time), the <time>'s title. */
  title: string;
  className?: string;
}

// A figure, a unit word, or the text between them, in a clock message.
export const PARTS = /<f>\{(days|hours|minutes)\}<\/f>|<u>([^<]*)<\/u>|([^<]+)/g;

/**
 * The ticking part of DeadlineClock (P26): days, hours and minutes as figures (leading units that are zero left out),
 * each with its unit word where the language's message puts it, in one <time> whose text reads as the duration
 * ("6 d 14 h 23 min", "siku 6 saa 14 dak 23"). Counted on the page's app clock (useAppClock.ts), the server's figure
 * first. No live region. The look is the caller's className, keyed on data-clock, data-figure, data-unit and data-gap.
 */
export function ClockFigures({ until, now, labelWhenPast, tone, formats, title, className }: ClockFiguresProps) {
  const left = useTimeLeft(Date.parse(until), Date.parse(now));
  const { d, h, m } = splitLeft(left);
  return (
    <span data-clock={left > 0 ? (tone === "warm" && left < DAY ? "warm" : "open") : "past"} className={className}>
      {left > 0 ? (
        <time dateTime={`P${d}DT${h}H${m}M`} title={title} suppressHydrationWarning>
          {/* Leading units that are zero are not drawn ("14 h 23 min", "23 min"): the message for the largest unit left. */}
          {[...formats[d ? 0 : h ? 1 : 2].matchAll(PARTS)].map(([, figure, unit, text], index) =>
            figure ? (
              <span key={index} data-figure="" suppressHydrationWarning>
                {{ days: d, hours: h, minutes: m }[figure as "days" | "hours" | "minutes"]}
              </span>
            ) : unit !== undefined ? (
              <span key={index} data-unit="">
                {unit}
              </span>
            ) : (
              <span key={index} data-gap="">
                {text}
              </span>
            ),
          )}
        </time>
      ) : (
        labelWhenPast
      )}
    </span>
  );
}
