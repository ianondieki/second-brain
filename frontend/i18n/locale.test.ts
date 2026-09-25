import { describe, expect, it } from "vitest";

import { resolveLocale, SWAHILI_LIVE } from "./locale";

describe("resolveLocale", () => {
  it("serves English to everyone until the Swahili review at G5", () => {
    expect(SWAHILI_LIVE).toBe(false);
    expect(resolveLocale("sw", "sw-KE,sw;q=0.9")).toBe("en");
    expect(resolveLocale(undefined, "sw")).toBe("en");
    expect(resolveLocale(null, null)).toBe("en");
  });

  it("will honour the cookie, then Accept-Language, once Swahili goes live", () => {
    expect(resolveLocale("sw", "en-GB", true)).toBe("sw");
    expect(resolveLocale(undefined, "sw-KE,en;q=0.8", true)).toBe("sw");
    expect(resolveLocale("fr", "de", true)).toBe("en");
  });
});
