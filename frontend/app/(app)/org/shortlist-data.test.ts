import { beforeEach, describe, expect, it, vi } from "vitest";

// REQ-REPO-02 (P21 B6): the proposal page's star reads its one shortlist entry. On the list (200) is on; not on it
// (404) and any other failure are off, so the page still renders; a lost session signs in again.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirect(path) }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { isShortlisted } = await import("./shortlist-data");

const ORG = "01a10b26-534a-717a-9846-cfb7ab5c200a";
const PROPOSAL = "01a10b26-6c6d-72f4-b780-bc3566431999";
const answer = (code: number, data?: unknown) => ({
  data,
  error: data ? undefined : { detail: { code: "x", message: "x" } },
  response: new Response(null, { status: code }),
});

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});

describe("isShortlisted", () => {
  it("reads the one entry, once, and is on when it exists", async () => {
    GET.mockResolvedValueOnce(answer(200, { proposal_id: PROPOSAL, available: true }));
    await expect(isShortlisted(ORG, PROPOSAL)).resolves.toBe(true);
    expect(GET).toHaveBeenCalledOnce();
    expect(GET).toHaveBeenCalledWith(
      "/api/orgs/{org_id}/shortlist/{proposal_id}",
      expect.objectContaining({ params: { path: { org_id: ORG, proposal_id: PROPOSAL } }, cache: "no-store" }),
    );
  });

  it("is off when the proposal is not on the list (404) and on any other failure", async () => {
    for (const code of [404, 403, 500, 503]) {
      GET.mockResolvedValueOnce(answer(code));
      await expect(isShortlisted(ORG, PROPOSAL)).resolves.toBe(false);
    }
    GET.mockRejectedValueOnce(Object.assign(new Error("The operation timed out."), { name: "TimeoutError" }));
    await expect(isShortlisted(ORG, PROPOSAL)).resolves.toBe(false);
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(isShortlisted(ORG, PROPOSAL)).resolves.toBe(false);
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(answer(401));
    await expect(isShortlisted(ORG, PROPOSAL)).rejects.toThrow("NEXT_REDIRECT /login");
  });
});
