import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { recommendations as answer } from "@/test/discover";

// REQ-PERS-01, REQ-TREND-02 (P12-F): the server calls behind Home's "Recommended for you" and the editor's
// `?problem=`. Home and the editor stand when these fail: every failure but a lost session is "nothing to show";
// 401 signs in again.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirect(path) }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { recommendations, savedSearches } = await import("./data");
const { linkableProblem } = await import("../ideas/data");

const status = (code: number, body?: unknown) => ({
  data: undefined,
  error: body ?? { detail: { code: "x", message: "x" } },
  response: new Response(null, { status: code }),
});
const timeout = () => Promise.reject(Object.assign(new Error("The operation timed out."), { name: "TimeoutError" }));

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});
afterEach(() => vi.clearAllMocks());

describe("Home's recommendations call", () => {
  it("gives the answer when the ranker answers", async () => {
    const body = answer();
    GET.mockResolvedValueOnce({ data: body, response: new Response(null, { status: 200 }) });
    await expect(recommendations()).resolves.toBe(body);
    expect(GET).toHaveBeenCalledWith("/api/me/recommendations", expect.objectContaining({ cache: "no-store" }));
  });

  it("is nothing to show on 500, on 404 (no developer profile), on a timeout and offline", async () => {
    GET.mockResolvedValueOnce(status(500));
    await expect(recommendations()).resolves.toBeNull();
    GET.mockResolvedValueOnce(status(404));
    await expect(recommendations()).resolves.toBeNull();
    GET.mockImplementationOnce(timeout);
    await expect(recommendations()).resolves.toBeNull();
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(recommendations()).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(recommendations()).rejects.toThrow("NEXT_REDIRECT /login");
    expect(redirect).toHaveBeenCalledWith("/login");
  });
});

describe("Discover's saved searches read (REQ-PERS-03)", () => {
  it("gives the list when the API answers", async () => {
    const body = { items: [], max: 10 };
    GET.mockResolvedValueOnce({ data: body, response: new Response(null, { status: 200 }) });
    await expect(savedSearches()).resolves.toBe(body);
    expect(GET).toHaveBeenCalledWith("/api/me/saved-searches", expect.objectContaining({ cache: "no-store" }));
  });

  it("is no strip (null), never a failed page, on 404, 500, 503, a timeout and offline", async () => {
    for (const code of [404, 500, 503]) {
      GET.mockResolvedValueOnce(status(code));
      await expect(savedSearches()).resolves.toBeNull();
    }
    GET.mockImplementationOnce(timeout);
    await expect(savedSearches()).resolves.toBeNull();
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(savedSearches()).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(savedSearches()).rejects.toThrow("NEXT_REDIRECT /login");
  });
});

describe("the editor's ?problem= lookup", () => {
  const ID = "01a0f067-b61f-7121-8f83-4293f5a2c7cd";

  it("links a published problem as the editor holds it", async () => {
    GET.mockResolvedValueOnce({
      data: {
        id: ID,
        title: "Tower sites go down when generators run dry",
        source: "developer",
        label: "Developer-reported",
        niche: { id: "n", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" },
        statement: "…",
        citations: [],
      },
      response: new Response(null, { status: 200 }),
    });
    await expect(linkableProblem(ID)).resolves.toEqual({
      id: ID,
      title: "Tower sites go down when generators run dry",
      source: "developer",
      label: "Developer-reported",
      niche: { id: "n", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" },
    });
    expect(GET).toHaveBeenCalledWith(
      "/api/problems/{problem_id}",
      expect.objectContaining({ params: { path: { problem_id: ID } } }),
    );
  });

  it("never fetches an id that is not a uuid", async () => {
    for (const id of ["", "abc", "../admin", `${ID}x`, "01a0f067-b61f-7121-8f83-4293f5a2c7c"]) {
      await expect(linkableProblem(id)).resolves.toBeNull();
    }
    expect(GET).not.toHaveBeenCalled();
  });

  it("links nothing for a foreign, held or unknown problem (404), a refused id (422), a failure or a timeout", async () => {
    for (const code of [404, 422, 500, 503]) {
      GET.mockResolvedValueOnce(status(code));
      await expect(linkableProblem(ID)).resolves.toBeNull();
    }
    GET.mockImplementationOnce(timeout);
    await expect(linkableProblem(ID)).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(linkableProblem(ID)).rejects.toThrow("NEXT_REDIRECT /login");
  });
});
