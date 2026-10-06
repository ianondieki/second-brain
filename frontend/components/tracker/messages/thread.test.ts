import { describe, expect, it } from "vitest";

import { message, LIMITS } from "@/test/messages";

import { contentTypeOf, fileProblem, postRefusal, refusedAttachmentId, reportRefusal, retryMinutes, uploadRefusal } from "./refusals";
import { fileSize, firstUnread, groupByDay, maxMegabytes, nairobiDay, prependOlder } from "./thread";

// REQ-ENG-11 (docs/spec/06 6.9 "Messages tab"): the thread's pure parts: day groups in Nairobi time, the "New" line,
// earlier pages, the files a person may attach, and the fixed sentence each refusal of the API gets.

const error = (code: string, extra: Record<string, unknown> = {}) => ({ detail: { code, message: "API words", ...extra } });

describe("day groups", () => {
  it("groups by the day in Nairobi, naming today and yesterday on the platform's clock", () => {
    const groups = groupByDay(
      [
        message({ id: "a", created_at: "2026-10-03T09:00:00Z" }),
        message({ id: "b", created_at: "2026-10-04T08:00:00Z" }),
        // 22:30 UTC is already the next day in Nairobi (UTC+3).
        message({ id: "c", created_at: "2026-10-04T22:30:00Z" }),
        message({ id: "d", created_at: "2026-10-05T06:00:00Z" }),
      ],
      "2026-10-05",
    );
    expect(groups.map((g) => [g.day, g.label, g.messages.map((m) => m.id)])).toEqual([
      ["2026-10-03", null, ["a"]],
      ["2026-10-04", "yesterday", ["b"]],
      ["2026-10-05", "today", ["c", "d"]],
    ]);
    expect(groups[0].date).toBe("3 Oct 2026");
    expect(nairobiDay("2026-10-04T21:00:00Z")).toBe("2026-10-05");
  });

  it("puts the New line above the first message by someone else since the read marker", () => {
    const items = [
      message({ id: "old", created_at: "2026-10-05T06:00:00Z" }),
      message({ id: "mine", created_at: "2026-10-05T07:00:00Z", mine: true }),
      message({ id: "new", created_at: "2026-10-05T08:00:00Z" }),
    ];
    expect(firstUnread(items, "2026-10-05T06:30:00Z")).toBe("new");
    expect(firstUnread(items, null)).toBe("old");
    expect(firstUnread(items, "2026-10-05T09:00:00Z")).toBeNull();
  });

  it("prepends an earlier page without showing a message twice", () => {
    const shown = [message({ id: "b" }), message({ id: "c" })];
    expect(prependOlder(shown, [message({ id: "a" }), message({ id: "b" })]).map((m) => m.id)).toEqual(["a", "b", "c"]);
  });
});

describe("files", () => {
  it("accepts the API's types, reading Markdown and text files by their ending when the browser gives no type", () => {
    expect(contentTypeOf({ name: "plan.md", type: "" })).toBe("text/markdown");
    expect(contentTypeOf({ name: "notes.TXT", type: "" })).toBe("text/plain");
    expect(contentTypeOf({ name: "a.md", type: "text/x-markdown" })).toBe("text/markdown");
    expect(fileProblem({ name: "plan.md", type: "", size: 10 }, LIMITS)).toBeNull();
    expect(fileProblem({ name: "deck.pptx", type: "application/vnd.ms-powerpoint", size: 10 }, LIMITS)).toBe("type");
    expect(fileProblem({ name: "empty.pdf", type: "application/pdf", size: 0 }, LIMITS)).toBe("empty");
    expect(fileProblem({ name: "big.pdf", type: "application/pdf", size: LIMITS.max_attachment_bytes + 1 }, LIMITS)).toBe("size");
    expect(maxMegabytes(LIMITS)).toBe(20);
  });

  it("writes sizes as people read them", () => {
    expect(fileSize(45)).toBe("1 kB");
    expect(fileSize(820_000)).toBe("820 kB");
    expect(fileSize(4_200_000)).toBe("4.2 MB");
  });
});

describe("refusals", () => {
  it("words each refusal of a post by its code, never by the API's message", () => {
    expect(postRefusal(422, error("contains_contact"))).toBe("containsContact");
    expect(postRefusal(409, error("thread_read_only"))).toBe("readOnly");
    expect(postRefusal(409, error("thread_not_open"))).toBe("notOpen");
    expect(postRefusal(403, error("thread_not_open"))).toBe("notOpen");
    expect(postRefusal(403, error("cannot_post"))).toBe("cannotPost");
    expect(postRefusal(409, error("attachment_pending"))).toBe("pending");
    expect(postRefusal(422, error("unknown_attachment"))).toBe("unknownFile");
    expect(postRefusal(422, error("attachment_infected"))).toBe("infected");
    expect(postRefusal(422, error("attachment_expired"))).toBe("expired");
    expect(postRefusal(429, error("too_many_messages"))).toBe("tooMany");
    // A body FastAPI refused (blank, too long): a validation list.
    expect(postRefusal(422, { detail: [{ loc: ["body", "body"], msg: "too long" }] })).toBe("invalid");
    expect(postRefusal(500, undefined)).toBe("generic");
  });

  it("words an upload's refusal, and keeps the refused record's id to remove it", () => {
    expect(uploadRefusal(422, error("unsupported_file"))).toBe("type");
    expect(uploadRefusal(413, error("too_large"))).toBe("size");
    expect(uploadRefusal(422, error("attachment_infected", { attachment_id: "f1" }))).toBe("infected");
    expect(refusedAttachmentId(error("attachment_infected", { attachment_id: "f1" }))).toBe("f1");
    expect(uploadRefusal(409, error("too_many_staged"))).toBe("staged");
    expect(uploadRefusal(429, error("upload_quota"))).toBe("limit");
    expect(uploadRefusal(409, error("thread_read_only"))).toBe("readOnly");
    expect(uploadRefusal(503, error("storage_unavailable"))).toBe("storage");
    expect(uploadRefusal(0, undefined)).toBe("failed");
  });

  it("words a report's refusal", () => {
    expect(reportRefusal(409, error("own_message"))).toBe("reportOwn");
    expect(reportRefusal(429, error("too_many_reports"))).toBe("reportLimit");
    expect(reportRefusal(500, undefined)).toBe("reportFailed");
  });

  it("says how many minutes until a limit lifts, from Retry-After or the body", () => {
    expect(retryMinutes(new Headers({ "Retry-After": "125" }), undefined)).toBe(3);
    expect(retryMinutes(null, error("too_many_messages", { retry_after_seconds: 30 }))).toBe(1);
    expect(retryMinutes(null, undefined)).toBe(1);
  });
});
