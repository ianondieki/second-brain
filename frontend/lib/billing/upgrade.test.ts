import { describe, expect, it } from "vitest";

import { billingHref, safeNext, upgradeHref, upgradePlanOf } from "./upgrade";

const ORG = "0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f";
const planLimit = (upgrade: unknown) => ({
  detail: { code: "plan_limit", message: "This needs a higher plan.", limit: 3, used: 3, upgrade },
});

describe("upgradePlanOf", () => {
  it("reads the next plan up from a 402 body", () => {
    expect(upgradePlanOf(planLimit({ plan: "dev_pro_monthly", url: "/billing/upgrade?plan=dev_pro_monthly" }))).toBe(
      "dev_pro_monthly",
    );
  });

  it("has none at the top of the ladder or in other bodies", () => {
    expect(upgradePlanOf(planLimit(null))).toBeNull();
    expect(upgradePlanOf({ detail: { code: "d1_required", message: "" } })).toBeNull();
    expect(upgradePlanOf(undefined)).toBeNull();
    expect(upgradePlanOf("Payment Required")).toBeNull();
  });

  it("never takes a plan code that could change the link", () => {
    for (const plan of ["dev_pro&next=//evil.example", "../admin", "DEV_PRO", "", 42, "a".repeat(41)]) {
      expect(upgradePlanOf(planLimit({ plan, url: "/billing/upgrade" })), String(plan)).toBeNull();
    }
  });
});

describe("safeNext", () => {
  it("keeps signed-in pages of this site", () => {
    expect(safeNext("/dev/ideas/0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f/edit?step=3")).toBe(
      "/dev/ideas/0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f/edit?step=3",
    );
    expect(safeNext("/org")).toBe("/org");
  });

  it.each([
    "https://evil.example/dev",
    "//evil.example/dev",
    "/dev//evil.example",
    "/\\evil.example",
    "/dev/../login",
    "/dev/./x",
    "/login",
    "/developer",
    "dev/ideas",
    "/dev/ideas#x",
    "/dev/ideas\t",
    "javascript:alert(1)",
  ])("refuses %s", (value) => {
    expect(safeNext(value)).toBeUndefined();
  });

  it("refuses anything but a short string", () => {
    expect(safeNext(undefined)).toBeUndefined();
    expect(safeNext(["/dev"])).toBeUndefined();
    expect(safeNext(`/dev/${"a".repeat(400)}`)).toBeUndefined();
  });
});

describe("upgradeHref and billingHref", () => {
  it("builds the checkout link from the plan code, with the organisation and the way back", () => {
    expect(upgradeHref("dev_pro_monthly")).toBe("/billing/upgrade?plan=dev_pro_monthly");
    expect(upgradeHref("org_starter", { org: ORG })).toBe(`/billing/upgrade?plan=org_starter&org=${ORG}`);
    expect(upgradeHref("dev_pro_monthly", { next: "/dev/ideas/x/edit?step=3" })).toBe(
      "/billing/upgrade?plan=dev_pro_monthly&next=%2Fdev%2Fideas%2Fx%2Fedit%3Fstep%3D3",
    );
  });

  it("drops an organisation or a way back that is not safe", () => {
    expect(upgradeHref("dev_pro_monthly", { org: "x", next: "//evil.example" })).toBe(
      "/billing/upgrade?plan=dev_pro_monthly",
    );
    expect(billingHref()).toBe("/billing");
    expect(billingHref("nope")).toBe("/billing");
    expect(billingHref(ORG)).toBe(`/billing?org=${ORG}`);
  });
});
