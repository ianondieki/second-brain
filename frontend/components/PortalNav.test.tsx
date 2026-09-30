import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PortalNav } from "./PortalNav";
import { HomeIcon, IdeasIcon } from "./ui/icons";

afterEach(cleanup);

const ITEMS = [
  { key: "home", href: "/dev", label: "Home", Icon: HomeIcon },
  { key: "ideas", href: "/dev/ideas", label: "My ideas", Icon: IdeasIcon },
];

// docs/spec/07 item 1, AC-UX-1: one portal navigation (bottom tabs on phones, a rail from 1024 px) behind DevNav,
// OrgNav and AdminNav; the current section is marked for assistive tech and by more than colour.
describe("PortalNav", () => {
  it("is a named navigation with a fixed tab bar on phones and a rail from 1024 px", () => {
    render(<PortalNav label="Developer" items={ITEMS} current="ideas" />);
    const nav = screen.getByRole("navigation", { name: "Developer" });
    expect(nav.hasAttribute("data-tab-bar")).toBe(true);
    expect(nav.className.split(" ")).toEqual(expect.arrayContaining(["fixed", "bottom-0", "lg:static", "lg:w-52"]));
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, "page"]);
    expect(links[1].querySelector("span[aria-hidden='true']")).not.toBeNull(); // the bar, not colour alone
    for (const link of links) expect(link.className).toContain("min-h-14");
  });

  it("keeps a query on every link", () => {
    render(<PortalNav label="Organisation" items={ITEMS} current="home" query="?org=1" />);
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/dev?org=1", "/dev/ideas?org=1"]);
  });

  it("shows no tab bar on phones for a single section, and nothing for none", () => {
    const { rerender } = render(<PortalNav label="Staff console" heading="Staff console" items={ITEMS.slice(0, 1)} />);
    const nav = screen.getByRole("navigation", { name: "Staff console" });
    expect(nav.hasAttribute("data-tab-bar")).toBe(false);
    expect(nav.className).toContain("hidden lg:block");
    expect(within(nav).getByText("Staff console", { selector: "p" }).className).toContain("lg:block");
    rerender(<PortalNav label="Staff console" items={[]} />);
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
