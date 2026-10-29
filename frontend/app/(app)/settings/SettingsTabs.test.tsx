import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { SettingsTabs } from "./SettingsTabs";

afterEach(cleanup);

// P16-A open item 9 (P16-C1): the two settings pages reach each other through one tab strip.
describe("SettingsTabs", () => {
  it("links Security and Notifications, marking the page shown", () => {
    renderWithIntl(<SettingsTabs current="notifications" />);
    const nav = screen.getByRole("navigation", { name: "Settings" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Security", "/settings/security"],
      ["Notifications", "/settings/notifications"],
    ]);
    expect(links[1].getAttribute("aria-current")).toBe("page");
    expect(links[0].hasAttribute("aria-current")).toBe(false);
  });

  // REQ-DEV-03: a developer has a third tab, Profile (the headline, the county and "Visible to peers").
  it("adds Profile for a developer only", () => {
    renderWithIntl(<SettingsTabs current="profile" developer />);
    const links = within(screen.getByRole("navigation", { name: "Settings" })).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Security", "/settings/security"],
      ["Notifications", "/settings/notifications"],
      ["Profile", "/settings/profile"],
    ]);
    expect(links[2].getAttribute("aria-current")).toBe("page");
  });
});
