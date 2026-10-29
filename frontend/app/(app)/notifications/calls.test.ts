import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";

import { markAllRead, markRead } from "./calls";

// P19-C: the page's two writes, POST /api/me/notifications/{id}/read and /read-all. Neither throws.

function client(post: (...args: unknown[]) => Promise<unknown>) {
  return { POST: vi.fn(post) } as unknown as ApiClient & { POST: ReturnType<typeof vi.fn> };
}

const answer = (status: number, data?: unknown) => async () => ({ data, response: new Response(null, { status }) });

describe("markRead", () => {
  it("posts the notification's id and answers whether it was recorded", async () => {
    const api = client(answer(200, { id: "n1" }));
    expect(await markRead("n1", api)).toBe(true);
    const [path, options] = api.POST.mock.calls[0] as [string, { params: unknown; signal: AbortSignal }];
    expect(path).toBe("/api/me/notifications/{notification_id}/read");
    expect(options.params).toEqual({ path: { notification_id: "n1" } });
    expect(options.signal).toBeInstanceOf(AbortSignal); // bounded: a hung API never holds the row
  });

  it("answers false for a refusal (another person's id is 404) and for a network failure", async () => {
    expect(await markRead("n1", client(answer(404)))).toBe(false);
    expect(await markRead("n1", client(async () => Promise.reject(new TypeError("offline"))))).toBe(false);
  });
});

describe("markAllRead", () => {
  it("posts read-all and answers whether the API marked them", async () => {
    const api = client(answer(200, { count: 0 }));
    expect(await markAllRead(api)).toBe(true);
    expect(api.POST.mock.calls[0][0]).toBe("/api/me/notifications/read-all");
    expect(await markAllRead(client(answer(403)))).toBe(false);
    expect(await markAllRead(client(async () => Promise.reject(new TypeError("offline"))))).toBe(false);
  });
});
