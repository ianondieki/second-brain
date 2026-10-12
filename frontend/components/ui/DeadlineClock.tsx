import { useLocale, useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { nairobiParts } from "@/lib/format";

import { ClockFigures } from "./ClockFigures";
import { cn } from "./cn";

// The figures in the figure face (Bricolage, tabular, bold, set solid), the unit words small and ink-soft beside each;
// under 24 hours on the viewer's own step ("warm"), the saffron mark before the figures (a pseudo-element, never read
// out) and the figures in the warm text colour; past the instant, the screen's word in the error colour. Here, on the
// server, not in the bundle; the page's ticker (ClockTicker.tsx) only changes data-clock and the figures.
const look = cn(
  "block leading-none whitespace-nowrap text-ink",
  "[&_[data-figure]]:font-figure [&_[data-figure]]:font-bold [&_[data-figure]]:tracking-[-0.02em] [&_[data-figure]]:tabular-nums",
  "[&_[data-unit]]:font-medium [&_[data-unit]]:text-ink-soft",
  "[&[data-clock=warm]_[data-figure]]:text-warm data-[clock=warm]:before:me-2 data-[clock=warm]:before:inline-block data-[clock=warm]:before:rounded-full data-[clock=warm]:before:bg-flourish data-[clock=warm]:before:align-middle",
  "data-[clock=past]:leading-snug data-[clock=past]:font-semibold data-[clock=past]:text-error",
);

const sizes = {
  // Cards: figures about 22 px over 12 px words.
  sm: "text-xs [&_[data-figure]]:text-[1.375rem] [&_[data-gap]]:ms-1 [&_[data-unit]]:mx-px data-[clock=warm]:before:size-2 data-[clock=past]:text-sm",
  // The tracker's figure panel: about 34 px on phones, 40 px from 640 px.
  lg: "text-sm [&_[data-figure]]:text-[2.125rem] sm:[&_[data-figure]]:text-[2.5rem] [&_[data-gap]]:ms-2 [&_[data-unit]]:mx-0.5 data-[clock=warm]:before:size-2.5 data-[clock=past]:text-base",
} as const;

export interface DeadlineClockProps {
  /** The instant the stage's window closes (the API's `due_at`). */
  until: string;
  /** The app clock's instant for this page (lib/api/server.ts appNow, from the API's X-App-Now). */
  now: string;
  /** Said in place of the figures once `until` is reached: the screen's existing word ("Overdue"). */
  labelWhenPast: string;
  /** The step is the viewer's: under 24 hours the figures take the saffron "your turn" look. */
  mine?: boolean;
  /** `sm` on cards, `lg` for the tracker's figure panel. */
  size?: keyof typeof sizes;
  /** The deadline in words under the figures ("4 business days left, due 16 Oct 2026"): what the figures picture. */
  words?: ReactNode;
  className?: string;
}

/**
 * The live deadline clock (P26; REQ-TRACK-03): the time left to `until` as a timer, days, hours and minutes in the
 * figure face with their unit words, drawn on the server (ClockFigures) and moved on the minute from the app clock by
 * the page's ticker (ClockTicker.tsx, which the page renders once), and the deadline in words as its line. The <time>
 * reads as the duration and carries the full instant in Nairobi time as its title; the words line says the date and the
 * business days. No live region. A server component wherever it is drawn: no JavaScript of its own.
 */
export function DeadlineClock({
  until,
  now,
  labelWhenPast,
  mine = false,
  size = "sm",
  words,
  className,
}: DeadlineClockProps) {
  const t = useTranslations("countdown");
  const locale = useLocale();
  const slots = {
    days: "{days}",
    hours: "{hours}",
    minutes: "{minutes}",
    f: (chunks: string) => `<f>${chunks}</f>`,
    u: (chunks: string) => `<u>${chunks}</u>`,
  };
  return (
    <div
      data-deadline-clock={size}
      className={cn("flex min-w-0 flex-col", size === "lg" ? "gap-2" : "gap-1.5", className)}
    >
      <ClockFigures
        until={until}
        now={now}
        labelWhenPast={labelWhenPast}
        tone={mine ? "warm" : "neutral"}
        // Each language's messages with their tags and slots kept for the figures to fill, here and by the ticker (order
        // and spacing are the message's own); formatted here, so they work however the catalogues are compiled.
        formats={[t.markup("clockDays", slots), t.markup("clockHours", slots), t.markup("clockMinutes", slots)]}
        title={t("at", nairobiParts(locale, until))}
        locale={locale}
        className={cn(look, sizes[size])}
      />
      {words ? <p className="text-sm leading-snug text-pretty text-ink-soft">{words}</p> : null}
    </div>
  );
}

// The sentence clock's look: tabular figures; on the viewer's own step under 24 hours, the saffron mark before the
// words and the time in the warm text colour (as the P23-3 countdown's).
const line =
  "tabular-nums data-[clock=warm]:before:me-1.5 data-[clock=warm]:before:inline-block data-[clock=warm]:before:size-2 data-[clock=warm]:before:rounded-full data-[clock=warm]:before:bg-flourish data-[clock=warm]:before:align-middle [&[data-clock=warm]>time]:font-semibold [&[data-clock=warm]>time]:text-warm";

export interface DeadlineLineProps {
  /** The instant the window closes (the API's `due_at`, a Brief's `deadline_at`). */
  until: string;
  /** The app clock's instant for this page (lib/api/server.ts appNow, from the API's X-App-Now). */
  now: string;
  /** Said once `until` is reached: the screen's existing wording ("Overdue", "Closed"). */
  labelWhenPast: string;
  /** "in 6 days 14 hours 23 minutes" (`in`) or "Proposals close in …" (`closesIn`). */
  sentence?: "in" | "closesIn";
  /** The step is the viewer's: under 24 hours the time takes the saffron "your turn" mark. */
  mine?: boolean;
  className?: string;
}

/**
 * The time left to `until` as a sentence ("in 6 days 14 hours 23 minutes", the units the language's own from Intl),
 * kept on the minute by the page's ticker as DeadlineClock is (P27): where a deadline is read, not watched (Home's
 * deadline tile, a Brief's closing, the organisation's line under an open question). The screen's word once the
 * instant has passed. The page renders the ticker (ClockTicker) once.
 */
export function DeadlineLine({
  until,
  now,
  labelWhenPast,
  sentence = "in",
  mine = false,
  className,
}: DeadlineLineProps) {
  const t = useTranslations("countdown");
  const locale = useLocale();
  return (
    <ClockFigures
      until={until}
      now={now}
      labelWhenPast={labelWhenPast}
      tone={mine ? "warm" : "neutral"}
      frame={t(sentence, { time: "{time}" })}
      title={t("at", nairobiParts(locale, until))}
      locale={locale}
      className={cn(line, className)}
    />
  );
}
