import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";

import { teamThreadCalls } from "./thread-calls";

// REQ-DEV-03 (P22-CF review): the team thread's calls word the API's answers as the engagement thread's parts do: a
// 429 with Retry-After in whole minutes, a closed thread, and each report refusal.

function client(answer: unknown): ApiClient {
  const call = vi.fn(async () => answer);
  return { GET: call, POST: call, PUT: call, PATCH: call, DELETE: call } as unknown as ApiClient;
}

const answer = (status: number, body?: unknown, headers?: Record<string, string>) => ({
  data: undefined,
  error: body,
  response: new Response(null, { status, headers }),
});

describe("the team thread's calls", () => {
  it("posts and gives the message in the thread's shape", async () => {
    const calls = teamThreadCalls("dev-b", client({ data: { id: "m1", mine: true, body: "Hi", redacted: false, created_at: "2026-10-06T10:00:00Z" }, response: new Response(null, { status: 201 }) }));
    const outcome = await calls.postMessage("t1", "Hi", []);
    expect(outcome).toEqual({ ok: true, message: expect.objectContaining({ id: "m1", sender_party: "developer", attachments: [] }) });
  });

  it("says the hourly limit with the minutes from Retry-After", async () => {
    const calls = teamThreadCalls("dev-b", client(answer(429, { detail: { code: "too_many_messages" } }, { "Retry-After": "150" })));
    await expect(calls.postMessage("t1", "Hi", [])).resolves.toEqual({ ok: false, refusal: "tooMany", minutes: 3 });
  });

  it("reads a closed thread as read-only, and a thrown fetch as the network", async () => {
    await expect(teamThreadCalls("dev-b", client(answer(409, { detail: { code: "thread_closed" } }))).postMessage("t1", "Hi", [])).resolves.toEqual({
      ok: false,
      refusal: "readOnly",
    });
    const offline = { POST: vi.fn(async () => Promise.reject(new TypeError("fetch failed"))) } as unknown as ApiClient;
    await expect(teamThreadCalls("dev-b", offline).postMessage("t1", "Hi", [])).resolves.toEqual({ ok: false, refusal: "network" });
  });

  it.each([
    [201, undefined, { ok: true, created: true }],
    [409, { detail: { code: "already_reported" } }, { ok: true, created: false }],
    [409, { detail: { code: "own_message" } }, { ok: false, refusal: "reportOwn" }],
    [429, { detail: { code: "too_many_reports" } }, { ok: false, refusal: "reportLimit" }],
    [500, undefined, { ok: false, refusal: "reportFailed" }],
  ])("words a report answered %s", async (status, body, outcome) => {
    const calls = teamThreadCalls("dev-b", client({ ...answer(status, body), data: status === 201 ? { case_id: "c1" } : undefined }));
    await expect(calls.reportMessage("t1", "m1", ["spam"])).resolves.toEqual(outcome);
  });

  it("files are refused (a team message has none)", async () => {
    const calls = teamThreadCalls("dev-b", client(answer(500)));
    await expect(calls.fileLink("t1", "m1", "a1")).resolves.toEqual({ ok: false, changed: false });
    await expect(calls.uploadFile("t1", new File(["x"], "a.txt"), { contentType: "text/plain" })).resolves.toEqual({ ok: false, problem: "failed" });
  });
});
