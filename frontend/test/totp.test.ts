import { describe, expect, it } from "vitest";

import { base32Decode, totp } from "../e2e/support/totp";

// The E2E suite trusts this helper to act like an authenticator app, so it is checked against RFC 6238 Appendix B.
const RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"; // base32 of the ASCII "12345678901234567890"

describe("E2E TOTP helper", () => {
  it("decodes base32", () => {
    expect(base32Decode(RFC_SECRET).toString("ascii")).toBe("12345678901234567890");
    expect(base32Decode("gezd gnbv").toString("ascii")).toBe("12345");
  });

  it.each([
    [59, "94287082"],
    [1111111109, "07081804"],
    [1111111111, "14050471"],
    [1234567890, "89005924"],
    [2000000000, "69279037"],
    [20000000000, "65353130"],
  ])("matches the RFC 6238 SHA-1 vector at T=%i", (seconds, expected) => {
    expect(totp(RFC_SECRET, { time: seconds * 1000, digits: 8 })).toBe(expected);
  });

  it("gives six digits by default and moves one window with offset 1", () => {
    expect(totp(RFC_SECRET, { time: 59_000 })).toBe("287082");
    expect(totp(RFC_SECRET, { time: 29_000, offset: 1 })).toBe(totp(RFC_SECRET, { time: 59_000 }));
  });
});
