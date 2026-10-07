import { useLocale, useTranslations } from "next-intl";

import { nairobiParts } from "@/lib/format";

import { cn } from "./cn";
import { Countdown } from "./Countdown";

// Tabular figures; under 24 hours on the viewer's own step ("warm"), the saffron mark before the words (decorative: a
// pseudo-element, never read out) and the figure in the warm text colour. Here, on the server, not in the bundle.
const look =
  "tabular-nums data-[timer=warm]:before:mr-1.5 data-[timer=warm]:before:inline-block data-[timer=warm]:before:size-2 data-[timer=warm]:before:rounded-full data-[timer=warm]:before:bg-flourish data-[timer=warm]:before:align-middle [&[data-timer=warm]>time]:font-semibold [&[data-timer=warm]>time]:text-warm";

export interface TimeLeftProps {
  /** The instant the window closes (the API's `due_at`, a Brief's `deadline_at`). */
  until: string;
  /** The app clock's instant for this page (lib/api/server.ts appNow, from the API's X-App-Now). */
  now: string;
  /** Said once `until` is reached: the screen's existing wording ("Overdue", "Closed"). */
  labelWhenPast: string;
  /** "6 d 14 h 23 m left" (`left`) or "Submissions close in 6 d 14 h 23 m" (`closesIn`). */
  sentence?: "left" | "closesIn";
  /** The step is the viewer's: under 24 hours the time takes the saffron "your turn" mark. */
  mine?: boolean;
  className?: string;
}

/**
 * The deadline countdown with its words (P23-3; REQ-TRACK-03): the messages in the page's language, their slots kept
 * for the ticking client part (components/ui/Countdown.tsx) to fill, and the full instant in Nairobi time as the
 * <time>'s title. A server component wherever it is drawn (a shared one under a client-rendered test, too).
 */
export function TimeLeft({ until, now, labelWhenPast, sentence = "left", mine = false, className }: TimeLeftProps) {
  const t = useTranslations("countdown");
  const locale = useLocale();
  const slots = { days: "{days}", hours: "{hours}", minutes: "{minutes}" };
  return (
    <Countdown
      until={until}
      now={now}
      labelWhenPast={labelWhenPast}
      tone={mine ? "warm" : "neutral"}
      units={[t("days", slots), t("hours", slots), t("minutes", slots)]}
      frame={t(sentence, { time: "{time}" })}
      title={t("at", nairobiParts(locale, until))}
      className={cn(look, className)}
    />
  );
}
