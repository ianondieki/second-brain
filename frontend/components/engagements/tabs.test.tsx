import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EngagementTabs, pickView, viewHref } from "./EngagementTabs";

// P27 (REQ-ENG-13, REQ-ENG-14; docs/spec/07 item 1): the Engagements page's views are tabs under its hero, never new
// navigation items: List (the default, unchanged) and Calendar for both sides, Board for an organisation.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
afterEach(cleanup);

describe("the views", () => {
  it("are read from ?view=, the list unless the portal has the view named", () => {
    expect(pickView(undefined, true)).toBe("list");
    expect(pickView("calendar", false)).toBe("calendar");
    expect(pickView("board", true)).toBe("board");
    expect(pickView("board", false)).toBe("list");
    expect(pickView(["calendar", "board"], true)).toBe("calendar");
    expect(pickView("nonsense", true)).toBe("list");
  });

  it("keep the organisation in their addresses, the list at the bare path", () => {
    expect(viewHref("/org/engagements", "list")).toBe("/org/engagements");
    expect(viewHref("/org/engagements", "list", { org: "o-1" })).toBe("/org/engagements?org=o-1");
    expect(viewHref("/org/engagements", "board", { org: "o-1", assignee: "me" })).toBe(
      "/org/engagements?view=board&org=o-1&assignee=me",
    );
    expect(viewHref("/dev/engagements", "calendar", { org: undefined })).toBe("/dev/engagements?view=calendar");
  });

  it("are one TabNav: two tabs for a developer, three for an organisation, the current one marked", async () => {
    renderWithIntl(<>{await resolveServerTree(<EngagementTabs basePath="/dev/engagements" current="calendar" />)}</>);
    let nav = screen.getByRole("navigation", { name: "Engagement views" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["List", "Calendar"]);
    expect(within(nav).getByRole("link", { name: "Calendar" }).getAttribute("aria-current")).toBe("page");
    cleanup();
    renderWithIntl(
      <>{await resolveServerTree(<EngagementTabs basePath="/org/engagements" current="board" board org="o-1" />)}</>,
    );
    nav = screen.getByRole("navigation", { name: "Engagement views" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["List", "/org/engagements?org=o-1"],
      ["Calendar", "/org/engagements?view=calendar&org=o-1"],
      ["Board", "/org/engagements?view=board&org=o-1"],
    ]);
  });
});
