import { describe, expect, it, vi } from "vitest";

import { markRead, postReadMarker } from "./mark-read";

// REQ-UX-05 (P25): marking a thread read runs as it opens, with the CSRF helper alone (the typed client loads with
// Send), so the messages routes stay within 150 KB; it stays quiet on a refusal or a network failure.

describe("markRead", () => {
  it("posts the newest seen message to the engagement's read marker", async () => {
    const send = vi.fn(async () => new Response(null, { status: 200 }));
    await expect(markRead("e/1", "m9", send)).resolves.toBe(true);
    expect(send).toHaveBeenCalledWith("/api/engagements/e%2F1/messages/read", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ up_to: "m9" }),
    });
  });

  it("answers false on a refusal and on a network failure, never throwing", async () => {
    const path = "/api/me/teams/{thread_id}/read";
    await expect(postReadMarker(path, "t1", "m1", async () => new Response(null, { status: 403 }))).resolves.toBe(false);
    await expect(postReadMarker(path, "t1", "m1", () => Promise.reject(new TypeError("offline")))).resolves.toBe(false);
  });

  it("fills a team thread's id into the schema's path", async () => {
    const send = vi.fn(async () => new Response(null, { status: 200 }));
    await postReadMarker("/api/me/teams/{thread_id}/read", "t 1", "m1", send);
    expect(send).toHaveBeenCalledWith("/api/me/teams/t%201/read", expect.objectContaining({ method: "POST" }));
  });
});
