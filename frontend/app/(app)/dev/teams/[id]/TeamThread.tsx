"use client";

import { useMemo } from "react";

import { Thread } from "@/components/tracker/messages/Thread";
import type { Thread as ThreadPage } from "@/components/tracker/messages/thread";

import { teamThreadCalls } from "./thread-calls";

/**
 * A team thread (REQ-DEV-03) drawn by the engagement thread's own parts (components/tracker/messages/Thread.tsx): the
 * messages by day with "New" above the first unread, earlier pages on request, Report on the other developer's
 * messages (the same sheet and reasons), the composer with Send as the screen's one primary action and no files.
 * Opening it marks the thread read. Only the calls differ (./thread-calls.ts).
 */
export function TeamThread({
  threadId,
  initial,
  counterpart,
  today,
  locale,
  empty,
}: {
  threadId: string;
  initial: ThreadPage;
  /** The other developer's handle: their messages' sender. */
  counterpart: string;
  today: string;
  locale: string;
  empty: string | null;
}) {
  const calls = useMemo(() => teamThreadCalls(counterpart), [counterpart]);
  return <Thread engagementId={threadId} initial={initial} today={today} locale={locale} orgName="" empty={empty} calls={calls} />;
}
