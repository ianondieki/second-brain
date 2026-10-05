import { beforeEach, describe, expect, it, vi } from "vitest";

// REQ-PERS-03 (P21 C6): the settings page's preferences read. Only a lost session leaves the page; any other failure
// is "no preferences", so the consents section still renders and saves.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirect(path) }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { myPreferences } = await import("./preferences-data");

const status = (code: number) => ({
  data: undefined,
  error: { detail: { code: "x", message: "x" } },
  response: new Response(null, { status: code }),
});

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});

describe("the notification preferences read", () => {
  it("gives the items when the API answers", async () => {
    const items = [{ kind: "saved_search_digest", channel: "email", label: "Digest", default: false, enabled: false }];
    GET.mockResolvedValueOnce({ data: { items }, response: new Response(null, { status: 200 }) });
    await expect(myPreferences()).resolves.toBe(items);
    expect(GET).toHaveBeenCalledWith("/api/me/notification-preferences", expect.objectContaining({ cache: "no-store" }));
  });

  it("is no preferences on 404, 500, 503, a timeout and offline", async () => {
    for (const code of [404, 500, 503]) {
      GET.mockResolvedValueOnce(status(code));
      await expect(myPreferences()).resolves.toEqual([]);
    }
    GET.mockRejectedValueOnce(Object.assign(new Error("The operation timed out."), { name: "TimeoutError" }));
    await expect(myPreferences()).resolves.toEqual([]);
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(myPreferences()).resolves.toEqual([]);
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(myPreferences()).rejects.toThrow("NEXT_REDIRECT /login");
  });
});
