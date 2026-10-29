import { describe, expect, it } from "vitest";

import { loginHref, mfaHref, returnPathParam, safeReturnPath } from "./return-path";

// P16-A open item 2 (P16-C1): the return path through /login and the second factor never leaves the site.
describe("safeReturnPath", () => {
  it("keeps this site's signed-in pages, with their query", () => {
    for (const path of [
      "/settings/notifications",
      "/dev",
      "/dev/ideas/0199a000-0000-7000-8000-0000000000aa/edit",
      "/dev/discover?view=projects&niche=dairy",
      "/org/inbox?org=0199a000-0000-7000-8000-00000000000b",
      "/billing/upgrade?plan=dev_pro_monthly",
      "/problems/0199a000-0000-7000-8000-000000000101",
      "/notifications",
      "/notifications?cursor=AbC_12-x",
    ]) {
      expect(safeReturnPath(path), path).toBe(path);
    }
  });

  it("refuses anything that could leave the site or is not a signed-in page", () => {
    for (const attempt of [
      "//evil.example",
      "//evil.example/dev",
      "https://evil.example/dev",
      "http:/evil.example",
      "/\\evil.example",
      "/\\/evil.example",
      "\\\\evil.example",
      "/%2F%2Fevil.example",
      "%2F%2Fevil.example",
      "/dev/%2e%2e/%2e%2e//evil.example",
      "/dev/../../evil",
      "/dev/./x",
      "/dev//evil.example",
      "/dev\t/x",
      "/dev\n/x",
      " /dev",
      "javascript:alert(1)",
      "data:text/html,x",
      "/login",
      "/",
      "/admin/moderation",
      "/devious",
      "/dev#x",
      "/dev?next=//evil.example",
      "dev",
      "",
      `/dev/${"a".repeat(300)}`,
      undefined,
      null,
      42,
      ["/dev"],
    ]) {
      expect(safeReturnPath(attempt), String(attempt)).toBeUndefined();
    }
  });

  it("builds the sign-in and second-factor addresses with it, or without it when unsafe", () => {
    expect(loginHref("/settings/notifications")).toBe("/login?next=%2Fsettings%2Fnotifications");
    expect(loginHref("//evil.example")).toBe("/login");
    expect(loginHref()).toBe("/login");
    expect(mfaHref("/dev/discover?view=gap")).toBe("/auth/mfa?next=%2Fdev%2Fdiscover%3Fview%3Dgap");
    expect(mfaHref("https://evil.example")).toBe("/auth/mfa");
  });

  it("reads a page's ?next= parameter, the first when repeated", () => {
    expect(returnPathParam("/dev")).toBe("/dev");
    expect(returnPathParam(["/org", "/dev"])).toBe("/org");
    expect(returnPathParam(["//evil", "/dev"])).toBeUndefined();
    expect(returnPathParam(undefined)).toBeUndefined();
  });
});
