import { describe, expect, it } from "vitest";

import { noticeKind } from "./kinds";

// D-67 (P25; REQ-UX-06: status is never colour alone): one icon per kind of notice, from the API's own kind codes.
describe("noticeKind", () => {
  it("names the tracker's notices, its messages, the scout and saved searches, reminders, events, teams and pitches", () => {
    expect(noticeKind("engagement.n03")).toBe("engagement");
    expect(noticeKind("engagement.tier2_shared")).toBe("engagement");
    expect(noticeKind("n17")).toBe("engagement");
    expect(noticeKind("engagement.n18")).toBe("message");
    expect(noticeKind("em3")).toBe("discover");
    expect(noticeKind("saved_search_match")).toBe("discover");
    expect(noticeKind("em7")).toBe("reminder");
    expect(noticeKind("em7_org")).toBe("reminder");
    expect(noticeKind("n27")).toBe("event");
    expect(noticeKind("team.n28")).toBe("team");
    expect(noticeKind("pitch_sent")).toBe("inbox");
  });

  it("draws anything else as a plain notice, never an error", () => {
    expect(noticeKind("something.new")).toBe("other");
    expect(noticeKind("")).toBe("other");
  });
});
