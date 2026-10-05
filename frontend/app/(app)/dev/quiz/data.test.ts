import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { board, quizToday as todayFixture } from "@/test/quiz";

// REQ-DEV-01 (P22-AF): the server reads behind Home's "Today's five" card, /dev/quiz and the board. Home stands
// whatever the quiz API says: a day without a set is the card's one sentence, any other failure leaves the card out;
// only a lost session (401) leaves Home.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({ redirect: (path: string) => redirect(path) }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { quizBoard, quizCard, quizToday } = await import("./data");

const status = (code: number, errorCode = "x") => ({
  data: undefined,
  error: { detail: { code: errorCode, message: "x" } },
  response: new Response(null, { status: code }),
});
const timeout = () => Promise.reject(Object.assign(new Error("The operation timed out."), { name: "TimeoutError" }));

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});
afterEach(() => vi.clearAllMocks());

describe("Home's quiz card read", () => {
  it("gives today's set", async () => {
    const today = todayFixture();
    GET.mockResolvedValueOnce({ data: today, response: new Response(null, { status: 200 }) });
    await expect(quizCard()).resolves.toEqual({ kind: "set", today });
    expect(GET).toHaveBeenCalledWith("/api/me/quiz/today", expect.objectContaining({ cache: "no-store" }));
  });

  it("is the no-quiz sentence on 404 no_quiz", async () => {
    GET.mockResolvedValueOnce(status(404, "no_quiz"));
    await expect(quizCard()).resolves.toEqual({ kind: "none" });
  });

  it("leaves the card out on any other 404, on 500, on a timeout and offline", async () => {
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(quizCard()).resolves.toBeNull();
    GET.mockResolvedValueOnce(status(500));
    await expect(quizCard()).resolves.toBeNull();
    GET.mockImplementationOnce(timeout);
    await expect(quizCard()).resolves.toBeNull();
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(quizCard()).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(quizCard()).rejects.toThrow("NEXT_REDIRECT /login");
  });
});

describe("the quiz page's and the board's reads", () => {
  it("gives the set or no set; anything else is the route's error page", async () => {
    GET.mockResolvedValueOnce(status(404, "no_quiz"));
    await expect(quizToday()).resolves.toEqual({ kind: "none" });
    GET.mockResolvedValueOnce(status(500));
    await expect(quizToday()).rejects.toThrow("answered 500");
    GET.mockResolvedValueOnce(status(401));
    await expect(quizToday()).rejects.toThrow("NEXT_REDIRECT /login");
  });

  it("reads this week's board", async () => {
    const week = board();
    GET.mockResolvedValueOnce({ data: week, response: new Response(null, { status: 200 }) });
    await expect(quizBoard()).resolves.toBe(week);
    expect(GET).toHaveBeenCalledWith("/api/me/quiz/leaderboard", expect.anything());
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(quizBoard()).rejects.toThrow("answered 404");
  });
});
