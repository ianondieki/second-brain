import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { CONSOLE_ROLES } from "@/lib/auth/routing";

import { ADMIN_SECTIONS, AdminNav, adminSections } from "./AdminNav";

afterEach(cleanup);

// docs/spec/07 item 1 and AC-UX-1: the staff console is its own portal with at most five items; each section is
// listed only for the staff roles the API admits to it (REQ-ADM-01; docs/spec/03 roles, bridge/admin/deps.py).
describe("AdminNav", () => {
  it("lists at most five sections: Research, Moderation, Claims, Quiz and Events for staff admins", () => {
    expect(ADMIN_SECTIONS.length).toBeLessThanOrEqual(5);
    renderWithIntl(<AdminNav current="moderation" role="admin" />);
    const nav = screen.getByRole("navigation", { name: "Staff console" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Research", "/admin/research"],
      ["Moderation", "/admin/moderation"],
      ["Claims", "/admin/claims"],
      ["Quiz", "/admin/quiz"],
      ["Events", "/admin/events"],
    ]);
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, "page", null, null, null]);
    // Several sections: bottom tabs on phones, the rail from 1024 px.
    expect(nav.hasAttribute("data-tab-bar")).toBe(true);
  });

  it("gives a moderator Moderation and Events (REQ-DEV-02), as tabs on phones", () => {
    renderWithIntl(<AdminNav current="moderation" role="moderator" />);
    const nav = screen.getByRole("navigation", { name: "Staff console" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Moderation", "Events"]);
    expect(links[0].getAttribute("aria-current")).toBe("page");
    expect(nav.hasAttribute("data-tab-bar")).toBe(true);
  });

  it("keeps the console roles of the sign-in routing in step with the sections", () => {
    const roles = new Set(ADMIN_SECTIONS.flatMap((section) => [...section.roles]));
    expect([...CONSOLE_ROLES].sort()).toEqual([...roles].sort());
  });

  it("shows a role only the sections the API admits it to", () => {
    expect(adminSections("admin").map((s) => s.key)).toEqual(["research", "moderation", "claims", "quiz", "events"]);
    expect(adminSections("moderator").map((s) => s.key)).toEqual(["moderation", "events"]);
    expect(adminSections("support")).toEqual([]);
    renderWithIntl(<AdminNav role="support" />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
