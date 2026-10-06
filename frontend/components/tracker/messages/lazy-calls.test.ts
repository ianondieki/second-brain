import { describe, expect, it, vi } from "vitest";

import type { ThreadCalls } from "./calls";
import { lazyCalls } from "./lazy-calls";

// REQ-DEV-03 / REQ-ENG-11 (P22-CF review): a thread's calls load on first use; when the module cannot be loaded each
// settles into its own failure value (never a thrown error), and marking read never waits for it.

describe("lazy thread calls", () => {
  it("loads the module on first use and calls through", async () => {
    const postMessage = vi.fn(async () => ({ ok: true as const, message: { id: "m" } as never }));
    const load = vi.fn(async () => ({ postMessage }) as unknown as ThreadCalls);
    const markRead = vi.fn(async () => true);
    const calls = lazyCalls(load, markRead);
    expect(load).not.toHaveBeenCalled();
    await calls.markRead("t", "m1");
    expect(load).not.toHaveBeenCalled();
    await expect(calls.postMessage("t", "Hi", [])).resolves.toEqual({ ok: true, message: { id: "m" } });
    expect(postMessage).toHaveBeenCalledWith("t", "Hi", []);
    expect(Object.keys(calls).sort()).toEqual(["fileLink", "markRead", "olderPage", "postMessage", "removeStaged", "reportMessage", "uploadFile"]);
  });

  it("settles into each call's failure when the module cannot be loaded", async () => {
    const calls = lazyCalls(() => Promise.reject(new TypeError("Failed to fetch dynamically imported module")), async () => true);
    await expect(calls.postMessage("t", "Hi", [])).resolves.toEqual({ ok: false, refusal: "network" });
    await expect(calls.olderPage("t", "c")).resolves.toEqual({ ok: false });
    await expect(calls.reportMessage("t", "m", ["spam"])).resolves.toEqual({ ok: false, refusal: "reportFailed" });
    await expect(calls.fileLink("t", "m", "a")).resolves.toEqual({ ok: false, changed: false });
    await expect(calls.removeStaged("t", "a")).resolves.toBe(false);
    await expect(calls.uploadFile("t", new File(["x"], "a.txt"), { contentType: "text/plain" })).resolves.toEqual({ ok: false, problem: "failed" });
  });
});
