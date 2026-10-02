import { getLocale, getTranslations } from "next-intl/server";

import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { RowBase, RowList } from "@/components/ui/RowBase";
import type { components } from "@/lib/api/schema";
import { formatDay, formatTime } from "@/lib/format";

import { groupByDay } from "./days";
import { ReadLink } from "./ReadLink";

export type Notification = components["schemas"]["NotificationOut"];

/**
 * The unread mark: a small accent diamond (the lattice's cut, D-52) before the title. Unread is also said in words
 * inside the title (for screen readers, so a link's name carries it) and by the title's weight: never by colour or
 * shape alone.
 */
function UnreadMark() {
  return <span aria-hidden="true" className="mt-[7px] inline-block size-2 shrink-0 rotate-45 rounded-[1px] bg-accent" />;
}

async function NotificationRow({ item }: { item: Notification }) {
  const [t, locale] = await Promise.all([getTranslations("notifications"), getLocale()]);
  const unread = item.read_at === null;
  const words = (
    <>
      {unread ? <span className="sr-only">{t("unread")}</span> : null}
      <span className={cn(unread ? "font-semibold text-ink" : "font-normal text-ink-soft")}>{item.title}</span>
    </>
  );
  return (
    <RowBase
      data-notification={item.id}
      data-unread={unread ? "true" : "false"}
      title={
        <span className="flex items-start gap-2.5">
          {unread ? <UnreadMark /> : <span aria-hidden="true" className="inline-block w-2 shrink-0" />}
          {item.link ? (
            <ReadLink
              id={item.id}
              href={item.link}
              unread={unread}
              // Stretched over the row: the whole row is the target, the title its name (as Row does).
              className={cn(titleLinkClass, "after:absolute after:inset-0")}
            >
              {words}
            </ReadLink>
          ) : (
            words
          )}
        </span>
      }
      figure={
        <time dateTime={item.created_at} className="text-sm whitespace-nowrap text-ink-soft">
          {t("time", { time: formatTime(locale, item.created_at) })}
        </time>
      }
    >
      {item.body ? <p className="max-w-[62ch] pl-[18px] text-sm [overflow-wrap:anywhere] text-ink-soft">{item.body}</p> : null}
    </RowBase>
  );
}

/** The notifications in Nairobi day groups (Today, Yesterday, then dates), each a heading and its rows, newest first. */
export async function NotificationList({ items, now }: { items: readonly Notification[]; now: Date }) {
  const [t, locale] = await Promise.all([getTranslations("notifications"), getLocale()]);
  return (
    <div className="flex flex-col gap-10">
      {groupByDay(items, now).map((group) => {
        const headingId = `day-${group.day}`;
        return (
          <section key={group.day} aria-labelledby={headingId} data-day={group.name}>
            <h2 id={headingId} className="mb-3 font-sans text-sm font-semibold tracking-[0.01em] text-ink-soft">
              {group.name === "date" ? formatDay(locale, group.at) : t(group.name)}
            </h2>
            <RowList aria-labelledby={headingId}>
              {group.items.map((item) => (
                <NotificationRow key={item.id} item={item} />
              ))}
            </RowList>
          </section>
        );
      })}
    </div>
  );
}
