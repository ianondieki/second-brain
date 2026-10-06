"use client";

import { useEffect, useMemo, useState, type ComponentType } from "react";

import { lazyCalls } from "@/components/tracker/messages/lazy-calls";
import { Thread } from "@/components/tracker/messages/Thread";
import type { Thread as ThreadPage } from "@/components/tracker/messages/thread";
import { api } from "@/lib/api/client";

import type { TeamCalls } from "../calls";
import { STEP_FAILED_ID, STEPS_ID } from "./ids";
import type { IdeaChoice, Sheet, ThreadSheets as Sheets } from "./ThreadSheets";

const load = () => import("./later");

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
 * #thread-steps): a press opens that step's dialog, whose status line then stays above the messages. Only the calls
 * differ from the engagement's (./thread-calls.ts).
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
  // The step pressed (a new n each press) and the dialogs' component, once loaded.
  const [sheet, setSheet] = useState<{ step: Sheet; n: number; Sheets: ComponentType<Parameters<typeof Sheets>[0]> } | null>(null);

  useEffect(() => {
    const stop = new AbortController();
    const press = (event: Event) => {
      // An open overflow menu closes as menus do (Escape, a press outside, an item's press): its code comes with the
      // steps' (./later), which an open menu is about to need.
      if (document.querySelector("details[data-overflow][open]")) void load().then((m) => m.closeOverflows(event), () => {});
      const step = event.type === "click" && (event.target as Element).closest<HTMLElement>(`#${STEPS_ID} [data-step]`)?.dataset.step;
      if (!step) return;
      // A step that cannot load (offline, a new deploy) shows the page's one sentence for it, which takes focus.
      const failed = document.getElementById(STEP_FAILED_ID);
      load().then(
        (m) => {
          if (failed) failed.hidden = true;
          setSheet((now) => ({ step: step as Sheet, n: (now?.n ?? 0) + 1, Sheets: m.ThreadSheets }));
        },
        () => {
          if (failed) failed.hidden = false;
          failed?.focus();
        },
      );
    };
    document.addEventListener("click", press, { signal: stop.signal });
    document.addEventListener("keydown", press, { signal: stop.signal });
    return () => stop.abort();
  }, []);

  return (
    <>
      {/* A step's dialog, and its status line once done, above the messages. */}
      {sheet ? <sheet.Sheets key={sheet.n} sheet={sheet.step} threadId={threadId} counterpart={person} ideas={ideas} calls={given} /> : null}
      <Thread engagementId={threadId} initial={initial} today={today} locale={locale} orgName="" empty={empty} calls={threadCalls} />
    </>
  );
}
