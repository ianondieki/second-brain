import { useLocale, useTranslations } from "next-intl";

import { nairobiParts } from "@/lib/format";

import { Countdown } from "./Countdown";

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
      className={className}
    />
  );
}
