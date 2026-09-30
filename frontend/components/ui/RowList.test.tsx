import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "./Badge";
import { Row, RowList } from "./RowList";

afterEach(cleanup);

// P16 design system, Lists of things: a hairline above the first row and between rows; each row a title (a link
// when it has a page), one meta line and at most two badges (docs/spec/07 item 2, AC-UX-1).
describe("RowList and Row", () => {
  it("puts a hairline above every row, the first included, and none around the list", () => {
    const { container } = render(
      <RowList aria-label="Ideas">
        <Row title="One" />
        <Row title="Two" />
      </RowList>,
    );
    const list = screen.getByRole("list", { name: "Ideas" });
    expect(list.className).not.toMatch(/\bborder/);
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row.className.split(" ")).toEqual(expect.arrayContaining(["border-t", "border-line"]));
    expect(container.querySelectorAll("article.py-5")).toHaveLength(2);
  });

  it("makes the title a link stretched over the row when the row has a page", () => {
    render(
      <RowList>
        <Row title="Cold chain for dairy co-ops" href="/dev/ideas/1" meta="Agriculture › Dairy" />
      </RowList>,
    );
    const link = screen.getByRole("link", { name: "Cold chain for dairy co-ops" });
    expect(link.getAttribute("href")).toBe("/dev/ideas/1");
    expect(link.className).toContain("after:absolute");
    expect(link.className).toContain("after:inset-0");
    expect(link.closest("article")?.className).toContain("relative");
    expect(screen.getByRole("heading", { level: 3 }).className).toContain("text-base");
    expect(screen.getByText("Agriculture › Dairy").className).toContain("text-ink-soft");
  });

  it("is ordered when asked", () => {
    render(
      <RowList ordered>
        <Row title="First" />
      </RowList>,
    );
    expect(screen.getByRole("list").tagName).toBe("OL");
  });

  it("shows a right-aligned figure in tabular figures", () => {
    render(
      <RowList>
        <Row title="Invoice" figure="KES 1,250,000" />
      </RowList>,
    );
    expect(screen.getByText("KES 1,250,000").className).toEqual(expect.stringContaining("tabular-nums"));
    expect(screen.getByText("KES 1,250,000").className).toEqual(expect.stringContaining("text-right"));
  });

  it("carries at most two badges: the type refuses a third before anything runs", () => {
    const { container } = render(
      <RowList>
        <Row
          title="Two badges"
          badges={[
            <Badge key="a" data-chip="stage">
              In review
            </Badge>,
            <Badge key="b" data-chip="turn" solid tone="accent">
              Your turn
            </Badge>,
          ]}
        />
      </RowList>,
    );
    expect(container.querySelectorAll("[data-chip]")).toHaveLength(2);
    // The dev-time check (docs/spec/07 item 2): `tsc` (npm run typecheck) fails on a third badge.
    const three = (
      <Row
        title="Three"
        // @ts-expect-error a row carries at most two badges
        badges={[<Badge key="a">A</Badge>, <Badge key="b">B</Badge>, <Badge key="c">C</Badge>]}
      />
    );
    expect(three).toBeTruthy();
  });
});
