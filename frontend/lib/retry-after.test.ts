import { describe, expect, it } from "vitest";

import { retryAfterSeconds, retryWhen } from "./retry-after";

// P28 review MAJOR 6: a 429 says roughly when to try again from the API's Retry-After, never a time it did not give.
describe("Retry-After", () => {
  it("reads seconds and HTTP dates, and nothing else", () => {
    expect(retryAfterSeconds("120")).toBe(120);
    expect(retryAfterSeconds("Wed, 14 Oct 2026 10:05:00 GMT", Date.parse("2026-10-14T10:00:00Z"))).toBe(300);
    expect(retryAfterSeconds(null)).toBeNull();
    expect(retryAfterSeconds("soon")).toBeNull();
  });

  it("rounds up to minutes, then to hours past one, and says later without a figure", () => {
    expect(retryWhen(5)).toEqual({ key: "minute" });
    expect(retryWhen(60)).toEqual({ key: "minute" });
    expect(retryWhen(61)).toEqual({ key: "minutes", count: 2 });
    expect(retryWhen(59 * 60)).toEqual({ key: "minutes", count: 59 });
    expect(retryWhen(3600)).toEqual({ key: "hour" });
    expect(retryWhen(3 * 3600 + 100)).toEqual({ key: "hours", count: 3 });
    expect(retryWhen(null)).toEqual({ key: "later" });
  });
});
