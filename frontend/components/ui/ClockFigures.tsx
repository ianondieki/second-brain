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
  /** The page's locale: the duration in words for screen readers ("6 days 14 hours 23 minutes") comes from Intl. */
  locale: string;
  className?: string;
}

// A figure, a unit word, or the text between them, in a clock message.
export const PARTS = /<f>\{(days|hours|minutes)\}<\/f>|<u>([^<]*)<\/u>|([^<]+)/g;

/** The duration in words for a screen reader (Intl's long units in the page's language: "siku 6 saa 14 dakika 23"). */
function spoken(locale: string, d: number, h: number, m: number): string {
  // Day, hour and minute are sanctioned units (ECMA-402) in every browser the browserslist names: no fallback.
  const unit = (value: number, kind: "day" | "hour" | "minute") =>
    new Intl.NumberFormat(locale, { style: "unit", unit: kind, unitDisplay: "long" }).format(value);
  const parts = [];
  if (d) parts.push(unit(d, "day"));
  if (d || h) parts.push(unit(h, "hour"));
  parts.push(unit(m, "minute"));
  return parts.join(" ");
}

/**
 * The ticking part of DeadlineClock (P26): days, hours and minutes as figures (leading units that are zero left out),
 * each with its unit word where the language's message puts it, in one <time> whose figures read as the duration
 * ("6 d 14 h 23 min", "siku 6 saa 14 dak 23") beside its words for screen readers. Counted on the page's app clock
 * (useAppClock.ts), the server's figure first. No live region. The look is the caller's className, keyed on
 * data-clock, data-figure, data-unit and data-gap; the figures sit under data-clock-figures, aria-hidden.
 */
export function ClockFigures({
  until,
  now,
  labelWhenPast,
  tone,
  formats,
  title,
  className,
  locale,
}: ClockFiguresProps) {
  const left = useTimeLeft(Date.parse(until), Date.parse(now));
  const { d, h, m } = splitLeft(left);
  return (
    <span data-clock={left > 0 ? (tone === "warm" && left < DAY ? "warm" : "open") : "past"} className={className}>
      {left > 0 ? (
        <time dateTime={`P${d}DT${h}H${m}M`} title={title} suppressHydrationWarning>
          {/* The duration in words for screen readers; the figures beside it are its picture (a letter "d" read out
              would not be). */}
          <span className="sr-only" suppressHydrationWarning>
            {spoken(locale, d, h, m)}
          </span>
          <span data-clock-figures="" aria-hidden="true">
            {/* Leading units that are zero are not drawn ("14 h 23 min", "23 min"): the message for the largest unit
                left. */}
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
          </span>
        </time>
      ) : (
        labelWhenPast
      )}
    </span>
  );
}
