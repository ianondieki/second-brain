import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TabNav } from "./TabNav";

afterEach(cleanup);

const ITEMS = [
  { key: "tracker", label: "Tracker", href: "/dev/engagements/1" },
  { key: "documents", label: "Documents", href: "/dev/engagements/1?tab=documents" },
  { key: "history", label: "History", href: "/dev/engagements/1?tab=history" },
] as const;

// P16 design system, Tabs: link tabs in a named <nav>, aria-current on the current one, 44 px targets, a 2 px
// accent bar on the current tab, and a strip that scrolls inside itself at 360 px.
describe("TabNav", () => {
  it("is a named navigation of links, in order", () => {
    render(<TabNav label="Engagement sections" items={ITEMS} current="tracker" />);
    const nav = screen.getByRole("navigation", { name: "Engagement sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual(
      ITEMS.map((item) => [item.label, item.href]),
    );
  });

  it("marks only the current tab, with the accent bar and weight, not colour alone", () => {
    render(<TabNav label="Views" items={ITEMS} current="documents" />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, "page", null]);
    const current = links[1].className.split(" ");
    expect(current).toEqual(expect.arrayContaining(["border-b-2", "border-accent", "text-ink", "font-bold"]));
    expect(links[0].className.split(" ")).toEqual(expect.arrayContaining(["border-transparent", "font-semibold", "text-ink-soft"]));
  });

  it("gives every tab a 44 px target and scrolls sideways inside itself", () => {
    render(<TabNav label="Views" items={ITEMS} current="tracker" />);
    for (const link of screen.getAllByRole("link")) expect(link.className).toContain("min-h-11");
    expect(screen.getByRole("list").className).toContain("overflow-x-auto");
  });
});
