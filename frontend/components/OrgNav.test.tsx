import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ORG_SECTIONS, OrgNav } from "./OrgNav";

afterEach(cleanup);

// docs/spec/07 item 1 and AC-UX-1: at most five items per portal; the current one is marked for assistive tech.
describe("OrgNav", () => {
  it("lists at most five sections, the Inbox and Engagements among them", () => {
    expect(ORG_SECTIONS.length).toBeLessThanOrEqual(5);
    renderWithIntl(<OrgNav current="inbox" />);
    const nav = screen.getByRole("navigation", { name: "Organisation" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Home", "/org"],
      ["Inbox", "/org/inbox"],
      ["Engagements", "/org/engagements"],
    ]);
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
