import type { ThreadCalls } from "./calls";

const LATER = ["postMessage", "olderPage", "reportMessage", "fileLink", "removeStaged", "uploadFile"] as const;

/**
 * A thread's calls with every one but `markRead` loaded on its first use (Send, earlier messages, Report, files):
 * marking read runs as the thread opens, so it is given at once; the rest stays out of the route's first load
 * (docs/spec/07 item 5, 150 KB per route). Own keys, so a caller may spread them.
 */
export function lazyCalls(load: () => Promise<ThreadCalls>, markRead: ThreadCalls["markRead"]): ThreadCalls {
  const calls: Record<string, unknown> = { markRead };
  for (const name of LATER) {
    calls[name] = async (...args: unknown[]) => ((await load())[name] as (...given: unknown[]) => unknown)(...args);
  }
  return calls as unknown as ThreadCalls;
}
