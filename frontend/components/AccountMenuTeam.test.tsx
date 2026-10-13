import { cleanup, fireEvent, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-TEN-02 (docs/spec/07 item 1): the organisation portal's five sections are taken, so Team is in the account menu
// on organisation screens, after Plan & billing, keeping the chosen organisation; never on the developer's or the
// console's screens. The tab bar itself stays at five (OrgNav.test.tsx).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

const { AccountMenu } = await import("./AccountMenu");
const { AccountMenuTeam, isOrgShell } = await import("./AccountMenuTeam");
const { ORG_SECTIONS } = await import("./OrgNav");

afterEach(cleanup);

describe("Team in the account menu", () => {
  it("belongs to the organisation portal's shells only", () => {
    expect(isOrgShell("/org")).toBe(true);
    expect(isOrgShell("/org?org=0199c000-0000-7000-8000-0000000000a1")).toBe(true);
    expect(isOrgShell("/dev")).toBe(false);
    expect(isOrgShell("/admin")).toBe(false);
    expect(isOrgShell("/organisation")).toBe(false);
  });

  it("follows Plan & billing and keeps the chosen organisation", async () => {
    const query = "?org=0199c000-0000-7000-8000-0000000000a1";
    const extra = await resolveServerTree(<AccountMenuTeam homeHref={`/org${query}`} />);
    renderWithIntl(<AccountMenu extra={extra} />);
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("link", { name: "Team" }).getAttribute("href")).toBe(`/org/team${query}`);
    const links = [...document.querySelectorAll("[data-account-menu] a")].map((a) => a.textContent);
    expect(links.slice(0, 3)).toEqual(["Plan & billing", "Team", "Sign-in security"]);
  });

  it("is not a sixth section of the portal", () => {
    expect(ORG_SECTIONS.length).toBe(5);
    expect(ORG_SECTIONS.map((s) => s.href)).not.toContain("/org/team");
  });
});
