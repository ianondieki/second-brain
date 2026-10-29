import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { getUnreadCount } from "@/lib/api/server";

import { cn } from "./ui/cn";
import { Icon, type IconProps } from "./ui/status-icons";

export const NOTIFICATIONS_HREF = "/notifications";

/** Above this the badge reads "99+" (the accessible name keeps the real number). */
export const BADGE_MAX = 99;

function BellIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5.25 13.75V9a4.75 4.75 0 0 1 9.5 0v4.75l1.25 1.5H4z" />
      <path d="M8.25 17.25a1.9 1.9 0 0 0 3.5 0" />
    </Icon>
  );
}

/**
 * The top bar's bell (docs/spec/07 item 1: portal switcher, bell, avatar menu): a link to /notifications, 44 px, with
 * the unread count as a small badge on the bell (none at 0 or when the count is unknown, "99+" above 99) and in the
 * link's accessible name ("Notifications, 3 unread"), and aria-current="page" on /notifications itself. Server-rendered
 * with the page, never polled; no client JS.
 */
export async function NotificationBell({ count, current = false }: { count: number | null; current?: boolean }) {
  const t = await getTranslations("notifications.bell");
  const unread = count !== null && count > 0 ? count : 0;
  return (
    <Link
      href={NOTIFICATIONS_HREF}
      prefetch={false}
      aria-current={current ? "page" : undefined}
      data-notification-bell=""
      className={cn(
        "relative inline-flex size-11 shrink-0 items-center justify-center rounded-control text-ink",
        "transition-colors duration-(--motion-fast) hover:bg-accent-wash motion-reduce:transition-none",
      )}
    >
      <BellIcon className="size-[22px]" />
      <span className="sr-only">{unread > 0 ? t("unread", { count: unread }) : t("label")}</span>
      {unread > 0 ? (
        <span
          aria-hidden="true"
          data-unread-badge=""
          className={cn(
            "absolute top-1 left-[22px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full",
            "bg-accent px-1 text-[11px] leading-none font-semibold tabular-nums text-on-accent ring-2 ring-paper",
          )}
        >
          {unread > BADGE_MAX ? t("overflow", { count: BADGE_MAX }) : unread}
        </span>
      ) : null}
    </Link>
  );
}

/** The bell with this request's unread count (GET /api/me/notifications/unread-count, shared per request). */
export async function UnreadNotificationBell({ current = false }: { current?: boolean }) {
  let count: number | null = null;
  try {
    count = await getUnreadCount();
  } catch {
    count = null; // a count that cannot be read never holds the top bar up: the bell shows none
  }
  return <NotificationBell count={count} current={current} />;
}
