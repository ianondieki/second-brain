import type { ThreadCalls } from "./calls";

// What each call settles into when its module could not be loaded (offline, a new deploy): the refusal the thread
// already words for a failed call, never a thrown error (Send would stay at "Sending…").
const FAILED = {
  postMessage: { ok: false, refusal: "network" },
  olderPage: { ok: false },
  reportMessage: { ok: false, refusal: "reportFailed" },
  fileLink: { ok: false, changed: false },
  removeStaged: false,
  uploadFile: { ok: false, problem: "failed" },
} as const;

/**
 * A thread's calls with every one but `markRead` loaded on its first use (Send, earlier messages, Report, files):
 * marking read runs as the thread opens, so it is given at once; the rest stays out of the route's first load
 * (docs/spec/07 item 5, 150 KB per route). Own keys, so a caller may spread them.
 */
export function lazyCalls(load: () => Promise<ThreadCalls>, markRead: ThreadCalls["markRead"]): ThreadCalls {
  const calls: Record<string, unknown> = { markRead };
  for (const [name, failed] of Object.entries(FAILED)) {
    calls[name] = async (...args: unknown[]) => {
      let call;
      try {
        call = (await load())[name as keyof typeof FAILED] as (...given: unknown[]) => unknown;
      } catch {
        return failed;
      }
      return call(...args);
    };
  }
  return calls as unknown as ThreadCalls;
}
