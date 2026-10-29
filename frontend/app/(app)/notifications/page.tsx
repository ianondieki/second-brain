import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { forwardHeaders, getUnreadCount, requireMe, serverApi } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

import { MarkAllRead } from "./MarkAllRead";
import { NotificationList, type Notification } from "./NotificationList";
import { FreshOnReturn } from "./ReadLink";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("notifications");
  return { title: t("pageTitle") };
}

const NOTIFICATIONS_PATH = "/notifications";

// Keyset cursors are the API's own (URL-safe base64); anything else is dropped before it reaches the API.
const CURSOR = /^[A-Za-z0-9_-]{1,500}$/;

type Page = { kind: "page"; items: Notification[]; next: string | null } | { kind: "staleCursor" };

/** One page of the signed-in person's notifications (GET /api/me/notifications), newest first, bounded in time. */
async function myNotifications(cursor: string | undefined): Promise<Page> {
  const { data, response } = await serverApi().GET("/api/me/notifications", {
    params: { query: cursor ? { cursor } : {} },
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (response.status === 401) redirect("/login"); // the session ended between the page's /me check and this call
  if (cursor && (response.status === 400 || response.status === 422)) return { kind: "staleCursor" };
  if (!data) throw new Error(`GET /api/me/notifications answered ${response.status}`);
  return { kind: "page", items: data.items, next: data.next_cursor };
}

/** "/notifications" with the next page's cursor. */
function pageHref(cursor?: string): string {
  return cursor ? `${NOTIFICATIONS_PATH}?${new URLSearchParams({ cursor }).toString()}` : NOTIFICATIONS_PATH;
}

/**
 * Notifications (docs/spec/07 item 1, the bell; REQ-NOT-03's in-app channel): the signed-in person's in-app
 * notifications, on either side, in Nairobi day groups, newest first, 20 a page. Opening a row marks it read and goes
 * where it points; "Mark all as read" is the one secondary action. The person's own portal navigation stays.
 */
export default async function NotificationsPage({ searchParams }: PageProps<"/notifications">) {
  const me = await requireMe();
  const home = homeOf(me);
  const params = await searchParams;
  const raw = Array.isArray(params.cursor) ? params.cursor[0] : params.cursor;
  const cursor = raw && CURSOR.test(raw) ? raw : undefined;
  const [t, tp, page, unread] = await Promise.all([
    getTranslations("notifications"),
    getTranslations("portal"),
    myNotifications(cursor),
    getUnreadCount(),
  ]);

  let body;
  if (page.kind === "staleCursor" || (cursor && page.items.length === 0)) {
    body = <EmptyState sentence={t("staleCursor")} action={t("newest")} href={NOTIFICATIONS_PATH} />;
  } else if (page.items.length === 0) {
    // What lands here differs by side: staff get moderation and research notices, organisations their proposals.
    const sentence = home === "/admin" ? t("emptyStaff") : home === "/org" ? t("emptyOrg") : t("empty");
    body = <EmptyState sentence={sentence} action={t("home")} href={home} />;
  } else {
    body = (
      <>
        <FreshOnReturn />
        <NotificationList items={page.items} now={new Date()} />
        {cursor || page.next ? (
          <nav aria-label={t("pages")} className="mt-10 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
            {cursor ? <StandaloneLink href={NOTIFICATIONS_PATH}>{t("newest")}</StandaloneLink> : <span />}
            {page.next ? <StandaloneLink href={pageHref(page.next)}>{t("older")}</StandaloneLink> : null}
          </nav>
        ) : null}
      </>
    );
  }

  // Unknown (the count did not answer in time): the unread rows on this page decide whether the action is open.
  const count = unread ?? (page.kind === "page" ? page.items.filter((item) => item.read_at === null).length : 0);
  return (
    <SignedInShell homeHref={home} nav={<PortalNavFor me={me} />} wide bellCurrent>
      <div className="max-w-3xl">
        <PageHero
          eyebrow={tp("eyebrow.notifications")}
          title={t("title")}
          lead={t("lead")}
          action={
            page.kind === "page" && page.items.length > 0 ? (
              <MarkAllRead
                unread={count}
                labels={{ idle: t("markAllRead"), busy: t("markingAllRead"), done: t("allRead"), failed: t("markAllFailed") }}
              />
            ) : null
          }
        />
        {body}
      </div>
    </SignedInShell>
  );
}
