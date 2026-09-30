import { describe, expect, it } from "vitest";

import { base32Decode, base32Encode, demoTotpSecret } from "../e2e/support/totp";

// The moderation E2E signs the demo staff in (P15-F): their keys must be the backend's (bridge/seed/demo/data.py).
describe("demo TOTP keys", () => {
  it("encodes base32 as RFC 4648 does, and round-trips", () => {
    expect(base32Encode(Buffer.from("12345678901234567890", "ascii"))).toBe("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ");
    expect(base32Encode(Buffer.from("f", "ascii"))).toBe("MY");
    const bytes = Buffer.from([0, 255, 17, 128, 64, 3, 250]);
    expect(base32Decode(base32Encode(bytes))).toEqual(bytes);
  });

  it("derives the backend's key for a demo address", () => {
    // python -c "from bridge.seed.demo.data import totp_secret; print(totp_secret('moderator@staff.example'))"
    expect(demoTotpSecret("moderator@staff.example")).toBe("ICGMJMELE63NODX36LK2GMNGPT3SFXNC");
    expect(demoTotpSecret(" Moderator@Staff.Example ")).toBe("ICGMJMELE63NODX36LK2GMNGPT3SFXNC");
  });
});
