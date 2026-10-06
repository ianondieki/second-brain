"use client";

import { lazyCalls } from "./lazy-calls";
import { markRead } from "./mark-read";
import { Thread, type ThreadProps } from "./Thread";

// The engagement's calls (./calls.ts), loaded with the first that needs them; marking read runs as the thread opens.
const calls = lazyCalls(() => import("./calls"), markRead);

/**
 * An engagement's thread (REQ-ENG-11): the thread with the engagement's own calls. They are lifted out of Thread so a
 * team thread (REQ-DEV-03, app/(app)/dev/teams/[id]) draws the same parts with its own calls and without these.
 */
export function EngagementThread(props: Omit<ThreadProps, "calls">) {
  return <Thread {...props} calls={calls} />;
}
