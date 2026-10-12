import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ChipMark } from "@/components/tracker/Chip";
import { DueText } from "@/components/tracker/When";
import { Badge } from "@/components/ui/Badge";
import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { DeadlineClock } from "@/components/ui/DeadlineClock";

import { icsHref } from "./data";
import { KindMark } from "./KindMark";
import { googleCalendarHref, isTurn, keyParts, type Deadline } from "./month";

const sr = (chunks: ReactNode) => <span className="sr-only">{chunks}</span>;
const calendarLinkClass =
  "inline-flex min-h-11 items-center text-sm font-semibold text-accent underline decoration-1 hover:decoration-2";

export interface DeadlineListProps {
  items: readonly Deadline[];
  /** The API's clock for the page (its `now`): the live clock counts from it. */
  now: string;
  /** Draw the live clock on the first item (the next thing due); every other item says its deadline in words. */
  clockFirst?: boolean;
  /** The organisation whose deadlines these are (its `.ics` route); none for the caller's own. */
  orgId?: string;
  /** The rows' heading level under the list's own heading. */
  headingLevel?: 3 | 4;
  /** Whose deadlines: the turn chip says "Your turn" to a developer, "Our turn" to an organisation. */
  side?: "developer" | "org";
}

/**
 * Deadlines as rows (P27 track A; REQ-ENG-13), server-rendered: the kind in words with its mark, the title as the one
 * link (the tracker, the Brief or the event), the other party or the Brief's or event's name, and the deadline: the
 * live clock on the next thing due (DeadlineClock, kept by the page's ticker), the business-days sentence elsewhere
 * (overdue in the error tone). "Your turn" is the one chip, on the viewer's own open steps (never an event's or a
 * Brief's). Each row puts its deadline in the person's calendar two ways, as the event page does (D-61): the `.ics`
 * file and a Google Calendar entry.
 */
export async function DeadlineList({
  items,
  now,
  clockFirst = false,
  orgId,
  headingLevel = 3,
  side = "developer",
}: DeadlineListProps) {
  const [t, tt] = await Promise.all([getTranslations("deadlines"), getTranslations("tracker")]);
  const Heading = headingLevel === 3 ? "h3" : "h4";
  return (
    <ul className="flex flex-col">
      {items.map((item, index) => {
        const { kind, id } = keyParts(item);
        const due = { due_on: item.due_on, business_days_left: item.business_days_left, overdue: item.overdue };
        const clock = clockFirst && index === 0 && !item.overdue && Date.parse(item.due_at) > Date.parse(now);
        return (
          <li key={item.key}>
            <article
              data-deadline={item.key}
              data-kind={item.kind}
              data-overdue={item.overdue ? "" : undefined}
              className="grid gap-x-6 gap-y-3 border-t border-line py-5 sm:grid-cols-[minmax(0,1fr)_auto]"
            >
              <div className="flex min-w-0 flex-col gap-1.5">
                <p className="flex items-center gap-1.5 text-sm font-semibold text-ink-soft">
                  <KindMark kind={item.kind} className="size-4 shrink-0" />
                  {t(`kind.${item.kind}`)}
                </p>
                <Heading className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
                  <Link href={item.href} className={cn(titleLinkClass, "-my-2.5 inline-flex min-h-11 items-center")}>
                    {item.title}
                  </Link>
                </Heading>
                <p className="text-sm [overflow-wrap:anywhere] text-ink-soft">{item.context}</p>
                {isTurn(item) ? (
                  <p>
                    <Badge tone="warm" solid data-chip="turn" icon={<ChipMark kind="current" />}>
                      {side === "org" ? tt("ourTurn") : t("yours")}
                    </Badge>
                  </p>
                ) : null}
              </div>
              <div className="flex min-w-0 flex-col gap-1 sm:items-end sm:text-end">
                {clock ? (
                  <DeadlineClock
                    until={item.due_at}
                    now={now}
                    labelWhenPast={tt("chip.overdue")}
                    mine={isTurn(item)}
                    words={<DueText due={due} />}
                    className="sm:items-end"
                  />
                ) : (
                  <DueText
                    due={due}
                    className={item.overdue ? "text-sm font-semibold text-error" : "text-sm text-ink-soft"}
                  />
                )}
                <p className="flex flex-wrap gap-x-5 sm:justify-end" data-calendar="">
                  <a href={icsHref(kind, id, orgId)} download className={calendarLinkClass} data-ics="">
                    {t.rich("addToCalendar", { title: item.title, sr })}
                  </a>
                  <a
                    href={googleCalendarHref(item, t("googleText", { title: item.title }), item.context)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={calendarLinkClass}
                    data-google=""
                  >
                    {t.rich("google", { title: item.title, sr })}
                  </a>
                </p>
              </div>
            </article>
          </li>
        );
      })}
    </ul>
  );
}
