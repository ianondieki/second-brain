"use client";

import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { lazyCalls } from "@/components/tracker/messages/lazy-calls";
import { Thread } from "@/components/tracker/messages/Thread";
import type { Thread as ThreadPage } from "@/components/tracker/messages/thread";
import { api } from "@/lib/api/client";

import type { TeamCalls } from "../calls";
import { STEP_STATUS_ID, STEPS_ID } from "./ids";
import type { IdeaChoice, Sheet } from "./ThreadSheets";

const load = () => import("./later");
const ThreadSheets = lazy(() => load().then((m) => ({ default: m.ThreadSheets })));

async function markRead(threadId: string, upTo: string) {
  try {
    const { response } = await api.POST("/api/me/teams/{thread_id}/read", { params: { path: { thread_id: threadId } }, body: { up_to: upTo } });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * A team thread (REQ-DEV-03) drawn by the engagement thread's own parts (components/tracker/messages/Thread.tsx): the
 * messages by day with "New" above the first unread, earlier pages on request, Report on the other developer's
 * messages (the same sheet and reasons), the composer with Send as the screen's one primary action and no files.
 * Opening it marks the thread read. It also answers the page's step buttons (StepButtons, server markup under
 * #thread-steps): a press opens that step's dialog in #thread-step-status, where its status line stays. Only the
 * calls differ from the engagement's (./thread-calls.ts).
 */
export function TeamThread({
  threadId,
  initial,
  counterpart,
  today,
  locale,
  empty,
  person,
  ideas,
  calls: given,
}: {
  threadId: string;
  initial: ThreadPage;
  /** The other developer's handle (their messages' sender). */
  counterpart: string;
  today: string;
  locale: string;
  empty: string | null;
  /** The other developer for the steps, or null when the caller may no longer see them. */
  person: { user_id: string; handle: string } | null;
  /** The caller's published ideas, which the other developer can be credited on. */
  ideas: readonly IdeaChoice[];
  /** Tests pass fakes for the steps; the real calls otherwise. */
  calls?: Partial<TeamCalls>;
}) {
  // The team calls (./thread-calls.ts) load with the first that needs them; marking read runs as the thread opens.
  const threadCalls = useMemo(() => lazyCalls(async () => (await load()).teamThreadCalls(counterpart), markRead), [counterpart]);
  const [sheet, setSheet] = useState<{ step: Sheet; n: number } | null>(null);

  useEffect(() => {
    const steps = document.getElementById(STEPS_ID);
    const press = (event: Event) => {
      const step = (event.target as Element).closest<HTMLElement>("[data-step]")?.dataset.step as Sheet | undefined;
      if (step) setSheet((now) => ({ step, n: (now?.n ?? 0) + 1 }));
    };
    steps?.addEventListener("click", press);
    return () => steps?.removeEventListener("click", press);
  }, []);

  const host = sheet ? document.getElementById(STEP_STATUS_ID) : null;
  return (
    <>
      {sheet && host
        ? createPortal(
            <Suspense fallback={null}>
              <ThreadSheets key={sheet.n} sheet={sheet.step} threadId={threadId} counterpart={person} ideas={ideas} calls={given} />
            </Suspense>,
            host,
          )
        : null}
      <Thread engagementId={threadId} initial={initial} today={today} locale={locale} orgName="" empty={empty} calls={threadCalls} />
    </>
  );
}
