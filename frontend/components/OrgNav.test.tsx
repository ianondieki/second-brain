import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { renderWithIntl } from "@/test/intl";

import { DEV_SECTIONS } from "./DevNav";
import { ORG_SECTIONS, OrgNav } from "./OrgNav";

afterEach(cleanup);

// docs/spec/07 item 1 and AC-UX-1: at most five items per portal; the current one is marked for assistive tech.
describe("OrgNav", () => {
  it("lists four sections: Home, Inbox, Engagements and Problems (REQ-DIR-05)", () => {
    expect(ORG_SECTIONS.length).toBeLessThanOrEqual(5);
    renderWithIntl(<OrgNav current="inbox" />);
    const nav = screen.getByRole("navigation", { name: "Organisation" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Home", "/org"],
      ["Inbox", "/org/inbox"],
      ["Engagements", "/org/engagements"],
      ["Problems", "/org/problems"],
    ]);
  });

  it("marks Problems as the current section on the Briefs screens", () => {
    renderWithIntl(<OrgNav current="problems" />);
    expect(screen.getByRole("link", { name: "Problems" }).getAttribute("aria-current")).toBe("page");
  });

  // The tab bar shares 360 px between its tabs (PortalNav). The developer's five tabs fit there in both languages
  // (e2e/navigation.spec.ts); the organisation's four take no more room: no label longer than the developer's longest,
  // and no more letters in all.
  it.each([
    ["en", en.nav],
    ["sw", sw.nav],
  ])("keeps its %s labels within what the developer's tab bar already fits at 360 px", (_, nav) => {
    const labels = (keys: readonly string[]) => keys.map((key) => nav[key as keyof typeof nav]);
    const org = labels(ORG_SECTIONS.map((s) => s.key));
    const dev = labels(DEV_SECTIONS.map((s) => s.key));
    for (const label of org) expect(label.trim().length).toBeGreaterThan(0);
    const longest = Math.max(...dev.map((label) => label.length));
    for (const label of org) expect(label.length, label).toBeLessThanOrEqual(longest);
    const total = (list: string[]) => list.reduce((sum, label) => sum + label.length, 0);
    expect(total(org)).toBeLessThanOrEqual(total(dev));
  });

  it("keeps the chosen organisation in every link", () => {
    renderWithIntl(<OrgNav current="engagements" query="?org=01a0ee62-0000-7000-8000-00000000000b" />);
    expect(screen.getByRole("link", { name: "Engagements" }).getAttribute("href")).toBe(
      "/org/engagements?org=01a0ee62-0000-7000-8000-00000000000b",
    );
    expect(screen.getByRole("link", { name: "Engagements" }).getAttribute("aria-current")).toBe("page");
  });

  it("marks only the current section", () => {
    renderWithIntl(<OrgNav current="inbox" />);
    expect(screen.getByRole("link", { name: "Inbox" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Home" }).hasAttribute("aria-current")).toBe(false);
  });
});
