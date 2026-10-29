import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Panel } from "./Panel";

afterEach(cleanup);

// P16 design system, Panels: the one bordered, rounded-panel box of a screen, or the wash side panel.
describe("Panel", () => {
  it("is a bordered white box by default", () => {
    render(<Panel data-testid="p">Assistant</Panel>);
    expect(screen.getByTestId("p").className.split(" ")).toEqual(
      expect.arrayContaining(["rounded-panel", "border", "border-line", "bg-field", "p-5", "sm:p-6"]),
    );
  });

  it("is the accent wash without a border as a side panel, named by its heading", () => {
    render(
      <Panel as="aside" variant="wash" aria-labelledby="how">
        <h2 id="how">How it works</h2>
      </Panel>,
    );
    const aside = screen.getByRole("complementary", { name: "How it works" });
    expect(aside.className.split(" ")).toEqual(expect.arrayContaining(["rounded-panel", "bg-accent-wash", "p-6", "lg:p-8"]));
    expect(aside.className.split(" ")).not.toContain("border");
  });
});
