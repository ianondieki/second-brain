import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DemoLocked } from "@/components/DemoLocked";
import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";
import { InfoIcon } from "@/components/ui/status-icons";
import { clientStrings } from "@/lib/i18n/client-strings";
import { publicDemoOn } from "@/lib/public-demo";

import type { ThreadRead } from "./data";
import { nairobiToday } from "./input";
import { HashFocus } from "./messages/HashFocus";
import { EngagementThread } from "./messages/EngagementThread";
import { isFinished, type Detail } from "./model";

/** The id of the thread's heading: the Messages route opens on it (…/messages#messages-heading; the N18 links too). */
export const MESSAGES_HEADING = "messages-heading";

/**
 * The tracker's Messages tab (REQ-ENG-11, AC-TRACK-9; docs/spec/06 6.9, docs/spec/07 items 1 and 4). Before
 * INTEREST_CONFIRMED one sentence says when the thread opens and the one action leads to the Tracker tab (the
 * organisation cannot read the thread then); an engagement that ended before that says so. Open, the thread and its
 * composer. After the end, or for a member whose role cannot write, the thread stays readable and one sentence stands
 * where the composer would be. The heading is the route's landing point (MESSAGES_HEADING).
 */
export async function MessagesTab({ detail, read, trackerHref }: { detail: Detail; read: ThreadRead; trackerHref: string }) {
  const t = await getTranslations("tracker");
  const developer = detail.my_party === "developer";
  const frame = { title: t("messages.title"), headingId: MESSAGES_HEADING, focusable: true, className: "[&_h2]:scroll-mt-6" };
  if (read.kind === "refused") {
    return (
      <Section {...frame} data-thread-state="refused">
        <HashFocus fallback={MESSAGES_HEADING} />
        <EmptyState rule={false} data-refusal={read.refusal} sentence={t(`refused.${read.refusal}`)} action={t("messages.toTracker")} href={trackerHref} />
      </Section>
    );
  }
  if (read.kind === "notOpen") {
    const ended = isFinished(detail.state);
    return (
      <Section {...frame} data-thread-state="not_open">
        <HashFocus fallback={MESSAGES_HEADING} />
        <EmptyState
          rule={false}
          data-thread-closed={ended ? "ended" : "not_open"}
          sentence={
            ended
              ? t("messages.endedBeforeOpen")
              : developer
                ? t("messages.notOpenDev", { org: detail.org_name })
                : t("messages.notOpenOrg")
          }
          action={t("messages.toTracker")}
          href={trackerHref}
        />
      </Section>
    );
  }
  const { thread } = read;
  const locale = await getLocale();
  const closed = thread.status === "read_only";
  // An ended thread with nothing in it has nothing to read: its sentence says only that no message can be sent.
  const empty = thread.items.length === 0 && !thread.next_cursor;
  const note = closed
    ? empty
      ? t("messages.readOnlyEmpty")
      : t("messages.readOnly")
    : thread.can_post
      ? null
      : t("messages.viewer");
  // The public demo (REQ-FND-04): file uploads are switched off. The composer is handed a thread that takes no files
  // (as a team thread's), so it draws no Attach and ships nothing new; one line under it says why. Server-side only:
  // the tracker routes sit at their 150 KB budget.
  const uploadsOff = publicDemoOn() && thread.can_post && !closed && thread.limits.max_attachments > 0;
  return (
    <Section
      {...frame}
      description={
        thread.can_post
          ? developer
            ? t("messages.leadDev", { org: detail.org_name })
            : t("messages.leadOrg", { name: detail.developer_name })
          : undefined
      }
      data-thread-state={thread.status}
    >
      <HashFocus fallback={MESSAGES_HEADING} />
      <ClientStrings strings={await clientStrings(["trackerMessages"])}>
        <EngagementThread
          engagementId={detail.id}
          initial={uploadsOff ? { ...thread, limits: { ...thread.limits, max_attachments: 0 } } : thread}
          today={detail.today ?? nairobiToday()}
          locale={locale}
          orgName={detail.org_name}
          // A closed thread's sentence is the note below: one sentence, not two.
          empty={closed ? null : thread.can_post ? t("messages.empty") : t("messages.emptyViewer")}
        />
      </ClientStrings>
      {uploadsOff ? (
        <DemoLocked sentence={(await getTranslations("publicDemo"))("attachLocked")} className="mt-4 text-sm" />
      ) : null}
      {note ? (
        <p className="mt-6 flex max-w-[65ch] items-start gap-2 text-ink" data-thread-closed={closed ? "read_only" : "viewer"}>
          <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
          <span>{note}</span>
        </p>
      ) : null}
    </Section>
  );
}
