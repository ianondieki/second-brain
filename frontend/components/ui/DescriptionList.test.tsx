import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Description, DescriptionList } from "./DescriptionList";

afterEach(cleanup);

// P16 design system, Label/value: one <dl> with the same label column on every screen (9–11 rem from 640 px,
// stacked below), tabular figures for amounts and dates.
describe("DescriptionList", () => {
  it("is a <dl> of label and value pairs", () => {
    render(
      <DescriptionList>
        <Description label="Name">Wanjiru Kamau</Description>
        <Description label="Phone">+254 700 000 000</Description>
      </DescriptionList>,
    );
    const terms = screen.getAllByRole("term");
    const values = screen.getAllByRole("definition");
    expect(terms.map((t) => t.textContent)).toEqual(["Name", "Phone"]);
    expect(values.map((v) => v.textContent)).toEqual(["Wanjiru Kamau", "+254 700 000 000"]);
    expect(terms[0].closest("dl")).not.toBeNull();
  });

  it("stacks under 640 px and keeps one label column from 640 px", () => {
    const { container } = render(
      <DescriptionList>
        <Description label="Stage">Agreement</Description>
      </DescriptionList>,
    );
    const dl = container.querySelector("dl")!;
    expect(dl.className).toContain("sm:grid-cols-[minmax(9rem,11rem)_minmax(0,1fr)]");
    expect(dl.className).not.toMatch(/(^|\s)grid-cols-/);
    expect(container.querySelector("dt")!.parentElement!.className).toContain("sm:contents");
  });

  it("sets amounts and dates in tabular figures when asked", () => {
    const { container, rerender } = render(
      <DescriptionList>
        <Description label="Amount">KES 250,000</Description>
      </DescriptionList>,
    );
    expect(container.querySelector("dl")!.className).not.toContain("tabular-nums");
    rerender(
      <DescriptionList figures>
        <Description label="Amount">KES 250,000</Description>
      </DescriptionList>,
    );
    expect(container.querySelector("dl")!.className).toContain("[&_dd]:tabular-nums");
  });
});
