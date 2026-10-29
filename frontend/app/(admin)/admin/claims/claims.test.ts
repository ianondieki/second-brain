import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import {
  CLAIM_VIEWS,
  claimHref,
  claimView,
  claimViewHref,
  orgName,
  shortId,
  slaChip,
  slaState,
  STATUS_CHIP,
} from "./claims";

describe("claims queue views (REQ-DIR-03 queue)", () => {
  it("opens the claims awaiting review unless another known view is asked for", () => {
    expect(claimView(undefined)).toBe("review");
    expect(claimView("in_progress")).toBe("in_progress");
    expect(claimView("closed")).toBe("closed");
    expect(claimView("decided")).toBe("review");
    expect(claimViewHref("review")).toBe("/admin/claims");
    expect(claimViewHref("in_progress")).toBe("/admin/claims?view=in_progress");
    expect(claimHref("01a0ee62-f783-733e-9321-9f34ec389ac2")).toBe(
      "/admin/claims/01a0ee62-f783-733e-9321-9f34ec389ac2",
    );
    const tabs = en.adminClaims.tabs as Record<string, string>;
    for (const view of CLAIM_VIEWS) expect(tabs[view], view).toBeTruthy();
  });
});

describe("the review SLA (2 business days, docs/spec/06 6.2)", () => {
  it("reads business days left, today, or overdue", () => {
    expect(slaState(null)).toBeNull();
    expect(slaState({ overdue: false, business_days_left: 2 })).toEqual({ kind: "due", days: 2 });
    expect(slaState({ overdue: false, business_days_left: 1 })).toEqual({ kind: "due", days: 1 });
    expect(slaState({ overdue: false, business_days_left: 0 })).toEqual({ kind: "today" });
    expect(slaState({ overdue: true, business_days_left: 0 })).toEqual({ kind: "overdue" });
    expect(slaState({ overdue: false, business_days_left: -1 })).toEqual({ kind: "overdue" });
  });

  it("marks an overdue claim with the warning mark, never colour alone", () => {
    expect(slaChip({ kind: "overdue" })).toBe("overdue");
    expect(slaChip({ kind: "today" })).toBe("current");
    expect(slaChip({ kind: "due", days: 2 })).toBe("current");
  });

  it("has a chip and a label for every claim status", () => {
    const labels = en.adminClaims.status as Record<string, string>;
    for (const status of Object.keys(STATUS_CHIP)) expect(labels[status], status).toBeTruthy();
  });
});

describe("organisations staff cannot read", () => {
  it("are named by id", () => {
    expect(orgName({ legal_name: "County Government of C (fixture)" })).toBe("County Government of C (fixture)");
    expect(orgName({ legal_name: null })).toBeNull();
    expect(orgName({ legal_name: "  " })).toBeNull();
    expect(shortId("01a0ee62-f783-733e-9321-9f34ec389ac2")).toBe("01a0ee62");
  });
});
