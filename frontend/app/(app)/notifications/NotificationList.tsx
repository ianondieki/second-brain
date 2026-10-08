import { getLocale, getTranslations } from "next-intl/server";

import { titleLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { RowBase, RowList } from "@/components/ui/RowBase";
import type { components } from "@/lib/api/schema";
import { formatDay, formatTime } from "@/lib/format";

import { CalendarIcon, InboxIcon } from "@/components/org-icons";
import { DiscoverIcon } from "@/components/discover-icons";
import { EngagementsIcon, MessageIcon } from "@/components/tracker/icons";
import { CompaniesIcon } from "@/components/ui/icons";
import { ClockIcon, InfoIcon } from "@/components/ui/status-icons";

import { groupByDay } from "./days";
import { noticeKind, type NoticeKind } from "./kinds";
import { ReadLink } from "./ReadLink";

export type Notification = components["schemas"]["NotificationOut"];

const KIND_ICON: Record<NoticeKind, typeof InfoIcon> = {
  message: MessageIcon,
  engagement: EngagementsIcon,
  discover: DiscoverIcon,
  reminder: ClockIcon,
  event: CalendarIcon,
  team: CompaniesIcon,
  inbox: InboxIcon,
  other: InfoIcon,
};

/**
 * What the notice is about, as an icon in a petal disc (D-67, P25; decorative: the title says it), with the unread mark
 * on its corner: a small accent diamond (the lattice's cut, D-52). Unread is also said in words inside the title (for
 * screen readers, so a link's name carries it) and by the title's weight: never by colour or shape alone.
 */
function KindMark({ kind, unread }: { kind: string; unread: boolean }) {
  const key = noticeKind(kind);
  const Icon = KIND_ICON[key];
  return (
    <span aria-hidden="true" className="notice-mark" data-kind={key} data-unread={unread ? "" : undefined}>
      <Icon className="size-[18px]" />
    </span>
  );
}

async function NotificationRow({ item }: { item: Notification }) {
  const [t, locale] = await Promise.all([getTranslations("notifications"), getLocale()]);
  const unread = item.read_at === null;
  const time = t("time", { time: formatTime(locale, item.created_at) });
  const words = (
    <>
      {unread ? <span className="sr-only">{t("unread")}</span> : null}
      <span className={cn(unread ? "font-semibold text-ink" : "font-normal text-ink-soft")}>{item.title}</span>
    </>
  );
  return (
    <RowBase
      className="notice-row"
      data-notification={item.id}
      data-unread={unread ? "true" : "false"}
      title={
        <span className="flex items-start gap-3">
          <KindMark kind={item.kind} unread={unread} />
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
      // Phones give the body the row's width: the time sits under the title there (only one of the two is ever shown,
      // so a screen reader hears it once), beside the title from 640 px.
      figure={
        <time dateTime={item.created_at} className="text-sm whitespace-nowrap text-ink-soft">
          {time}
        </time>
      }
      figureFrom="sm"
    >
      <time dateTime={item.created_at} className="pl-12 text-sm text-ink-soft sm:hidden">
        {time}
      </time>
      {item.body ? <p className="max-w-[62ch] pl-12 text-sm [overflow-wrap:anywhere] text-ink-soft">{item.body}</p> : null}
    </RowBase>
  );
}

/**
 * The notifications in Nairobi day groups (Today, Yesterday, then dates), newest first: each day a separator that
 * stays at the top while its rows scroll (the day's name in the mono face, a hairline after it), then its rows on a
 * card. Rows off screen are not drawn until they come near (`content-visibility`, portal.css .notice-row).
 */
export async function NotificationList({ items, now }: { items: readonly Notification[]; now: Date }) {
  const [t, locale] = await Promise.all([getTranslations("notifications"), getLocale()]);
  return (
    <div className="flex flex-col gap-8">
      {groupByDay(items, now).map((group) => {
        const headingId = `day-${group.day}`;
        return (
          <section key={group.day} aria-labelledby={headingId} data-day={group.name}>
            <h2 id={headingId} className="notice-day">
              <span>{group.name === "date" ? formatDay(locale, group.at) : t(group.name)}</span>
            </h2>
            {/* A day's rows on one white card (P20): the day is one object, its rows a list inside it. */}
            <RowList aria-labelledby={headingId} rule={false} className="rounded-panel border border-line bg-field px-4 sm:px-5">
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
