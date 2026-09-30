import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RowBase, RowList } from "./RowBase";

afterEach(cleanup);

// The link-free half of RowList (its figure columns, badges cap and hairlines are RowList.test.tsx's): the row's
// heading, meta line, badges and extra content, and the list's handling of absent children.
describe("RowBase", () => {
  it("renders the title as a level-3 heading by default, or level 2, with the id an aria-labelledby can use", () => {
    render(
      <>
        <RowBase title="Default level" />
        <RowBase title="Page-level row" headingLevel={2} titleId="row-title" />
      </>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Default level" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Page-level row" }).id).toBe("row-title");
  });

  it("reads title, meta line, badges in order, then the row's own content, with attributes on the article", () => {
    render(
      <RowBase
        title="Solar kiosks"
        meta="Energy › Off-grid · Kisumu"
        badges={[<span key="a">Submitted</span>, <span key="b">Your turn</span>]}
        data-row="proposal"
        aria-label="Solar kiosks row"
      >
        <p>Saved for 2 organisations</p>
      </RowBase>,
    );
    const row = screen.getByRole("article", { name: "Solar kiosks row" });
    expect(row.getAttribute("data-row")).toBe("proposal");
    const texts = [...row.querySelectorAll("h3, p, span")].map((el) => el.textContent);
    expect(texts).toEqual(["Solar kiosks", "Energy › Off-grid · Kisumu", "Submitted", "Your turn", "Saved for 2 organisations"]);
    expect(within(row).getByText("Energy › Off-grid · Kisumu").className).toContain("text-ink-soft");
  });

  it("leaves out the meta line, badges and figure when there are none", () => {
    const { container } = render(<RowBase title="Bare" />);
    const article = container.querySelector("article")!;
    expect(article.querySelectorAll("p")).toHaveLength(0);
    expect(article.children).toHaveLength(1); // the text column only: no figure column
  });
});

describe("RowList (RowBase module)", () => {
  it("gives each present child its own list item and skips absent ones", () => {
    const hidden = false;
    render(
      <RowList aria-label="Preview">
        <RowBase title="One" />
        {null}
        {hidden && <RowBase title="Never" />}
        {undefined}
        <RowBase title="Two" />
      </RowList>,
    );
    const items = within(screen.getByRole("list", { name: "Preview" })).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["One", "Two"]);
  });
});
