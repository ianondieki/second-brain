import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { DEV_SECTIONS, DevNav } from "./DevNav";

afterEach(cleanup);

// docs/spec/07 item 1 and AC-UX-1: at most five items per portal; the current one is marked for assistive tech.
describe("DevNav", () => {
  it("lists at most five sections in the spec's order, Discover, My ideas, Engagements and Companies among them", () => {
    expect(DEV_SECTIONS.length).toBeLessThanOrEqual(5);
    renderWithIntl(<DevNav current="companies" />);
    const nav = screen.getByRole("navigation", { name: "Developer" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Home", "/dev"],
      ["Discover", "/dev/discover"],
      ["My ideas", "/dev/ideas"],
      ["Engagements", "/dev/engagements"],
      ["Companies", "/dev/companies"],
    ]);
  });

  it("marks only the current section", () => {
    renderWithIntl(<DevNav current="companies" />);
    expect(screen.getByRole("link", { name: "Companies" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Home" }).hasAttribute("aria-current")).toBe(false);
    expect(screen.getByRole("link", { name: "My ideas" }).hasAttribute("aria-current")).toBe(false);
  });
});
