import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ProblemLabelText } from "./ProblemLabelText";

afterEach(cleanup);

// The idea page lists its linked problems with this label (P16-C1 fix round 1, reviewer MAJOR 1).
describe("ProblemLabelText", () => {
  it("renders nothing for an archived research card the API sends without a label", () => {
    const { container } = renderWithIntl(
      <ProblemLabelText problem={{ source: "research_agent", label: null, seeded_example: false, published_at: null }} />,
    );
    expect(container.querySelector("[data-label]")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("words a published card as the problem page does", () => {
    const { container } = renderWithIntl(
      <ProblemLabelText
        problem={{ source: "research_agent", label: "x", seeded_example: false, published_at: "2026-09-29T22:30:00Z" }}
      />,
    );
    expect(container.querySelector("[data-label]")?.textContent).toBe("AI-drafted, human-reviewed on 30 Sep 2026");
  });
});
