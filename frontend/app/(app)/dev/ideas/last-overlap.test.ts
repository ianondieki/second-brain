import { afterEach, describe, expect, it, vi } from "vitest";

import { NONE } from "@/test/checks";

// P19-F (REQ-PROP-04): the editor page's read of today's last overlap check. Best effort: whatever goes wrong, the
// editor opens without it (the owner can run the check again); never a redirect or an error page.

const GET = vi.fn();
const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirect(path) }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { lastOverlap } = await import("./data");

const ID = "01a0f067-b61f-7121-8f83-4293f5a2c7cd";
const refused = (code: number) => ({
  data: undefined,
  error: { detail: { code: "x", message: "x" } },
  response: new Response(null, { status: code }),
});

afterEach(() => {
  GET.mockReset();
  redirect.mockClear();
});

describe("lastOverlap", () => {
  it("gives today's last answer", async () => {
    GET.mockResolvedValueOnce({ data: NONE, response: new Response(null, { status: 200 }) });
    await expect(lastOverlap(ID)).resolves.toBe(NONE);
    expect(GET).toHaveBeenCalledWith(
      "/api/me/proposals/{proposal_id}/originality",
      expect.objectContaining({ params: { path: { proposal_id: ID } }, cache: "no-store" }),
    );
  });

  it("is null when there is no check today (a JSON null)", async () => {
    GET.mockResolvedValueOnce({ data: null, response: new Response("null", { status: 200 }) });
    await expect(lastOverlap(ID)).resolves.toBeNull();
  });

  it.each([404, 429, 500, 401])("is null on %i, without leaving the page", async (code) => {
    GET.mockResolvedValueOnce(refused(code));
    await expect(lastOverlap(ID)).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("is null when the fetch throws (offline, a timeout)", async () => {
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(lastOverlap(ID)).resolves.toBeNull();
    GET.mockImplementationOnce(() =>
      Promise.reject(Object.assign(new Error("The operation timed out."), { name: "TimeoutError" })),
    );
    await expect(lastOverlap(ID)).resolves.toBeNull();
  });

  it("never asks about an id that is not a proposal id", async () => {
    await expect(lastOverlap("not-an-id")).resolves.toBeNull();
    expect(GET).not.toHaveBeenCalled();
  });
});
