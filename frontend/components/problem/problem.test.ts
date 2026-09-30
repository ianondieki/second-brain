import { describe, expect, it } from "vitest";

import {
  formatConfidence,
  formatDate,
  formatLongDay,
  problemHref,
  problemLabel,
  safeHttpsUrl,
  sourceType,
} from "./problem";

describe("problemLabel (REQ-RES-02, docs/spec/06 6.5)", () => {
  const published = "2026-09-29T22:30:00Z"; // 30 September in Nairobi (UTC+3)

  it("labels a published research card AI-drafted with its Nairobi publication day", () => {
    expect(problemLabel({ source: "research_agent", seeded_example: false, published_at: published }, "en")).toEqual({
      key: "aiDrafted",
      date: "30 September 2026",
    });
  });

  it("never labels a demo seed card AI-drafted", () => {
    expect(problemLabel({ source: "research_agent", seeded_example: true, published_at: published }, "en")).toEqual({
      key: "seeded",
      date: "30 September 2026",
    });
  });

  it("labels a developer's problem and nothing else", () => {
    expect(problemLabel({ source: "developer", seeded_example: false, published_at: null }, "en")).toEqual({
      key: "developer",
    });
    expect(problemLabel({ source: "org_brief", seeded_example: false, published_at: published }, "en")).toBeNull();
    expect(problemLabel({ source: "research_agent", seeded_example: false, published_at: null }, "en")).toBeNull();
  });
});

describe("dates and numbers", () => {
  it("writes a calendar date without shifting it a day", () => {
    expect(formatDate("en", "2026-09-28")).toBe("28 Sept 2026");
    expect(formatDate("en", "2026-01-01")).toBe("1 Jan 2026");
    expect(formatDate("en", "not a date")).toBe("not a date");
  });

  it("writes a moment as its Nairobi day", () => {
    expect(formatLongDay("en", "2026-09-30T21:30:00Z")).toBe("1 October 2026");
  });

  it("shows confidence to two places", () => {
    expect(formatConfidence("en", "0.720")).toBe("0.72");
    expect(formatConfidence("en", "0.4")).toBe("0.40");
    expect(formatConfidence("en", null)).toBeNull();
    expect(formatConfidence("en", "")).toBeNull();
    expect(formatConfidence("en", "abc")).toBeNull();
  });
});

describe("links", () => {
  it("draws only plain https links", () => {
    expect(safeHttpsUrl("https://www.sasra.go.ke/2026/07/16/x/")).toBe("https://www.sasra.go.ke/2026/07/16/x/");
    expect(safeHttpsUrl("http://www.sasra.go.ke/")).toBeNull();
    expect(safeHttpsUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpsUrl("data:text/html,hi")).toBeNull();
    expect(safeHttpsUrl("https://user:pw@example.com/")).toBeNull();
    expect(safeHttpsUrl("not a url")).toBeNull();
  });

  it("names the known source types and folds the rest", () => {
    expect(sourceType("official")).toBe("official");
    expect(sourceType("news")).toBe("news");
    expect(sourceType("press_release")).toBe("other");
    expect(sourceType(null)).toBe("other");
  });

  it("builds the problem page's address from the id", () => {
    expect(problemHref("01a0f015-0feb-76bd-8eec-21b72f9f10e8")).toBe("/problems/01a0f015-0feb-76bd-8eec-21b72f9f10e8");
    expect(problemHref("a/b")).toBe("/problems/a%2Fb");
  });
});
