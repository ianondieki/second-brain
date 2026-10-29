import { describe, expect, it } from "vitest";

import { billingHref } from "@/lib/billing/upgrade";

import { menuBillingHref } from "./billing-link";

// The account menu builds "Plan & billing" without the checkout module; it must say exactly what billingHref says.
describe("menuBillingHref", () => {
  it("matches billingHref for an organisation id, nothing, and anything that is not an id", () => {
    for (const org of [
      undefined,
      "",
      "0199a000-0000-7000-8000-00000000000b",
      "0199A000-0000-7000-8000-00000000000B",
      "not-an-id",
      "0199a000-0000-7000-8000-00000000000b&plan=x",
      "https://evil.example",
      "../billing",
    ]) {
      expect(menuBillingHref(org), String(org)).toBe(billingHref(org));
    }
  });
});
