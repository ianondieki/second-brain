import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { tourScenes } from "./TourScenes";

// P23-2: each tour step's scene is decorative (the step's title and sentence say it), drawn from the product's parts
// with a vendored Lucide icon in the petal disc, and one lit thing.
afterEach(cleanup);

describe("tourScenes", () => {
  it.each(["developer", "org"] as const)("draws three decorative scenes for the %s side, each with its icon and one lit part", (side) => {
    const { container } = renderWithIntl(<>{tourScenes(side)}</>);
    const stages = [...container.querySelectorAll(".tour-stage")];
    expect(stages).toHaveLength(3);
    for (const stage of stages) {
      expect(stage.getAttribute("aria-hidden")).toBe("true");
      const icon = stage.querySelector(".tour-disc svg")!;
      expect(icon.getAttribute("viewBox")).toBe("0 0 24 24");
      expect(icon.getAttribute("stroke-width")).toBe("1.75");
      expect(stage.querySelectorAll(".tour-lit, [data-seal]").length).toBe(1);
    }
  });

  it("uses the product's own words: Need you, the certificate, Your turn, New, Confidential", () => {
    const dev = renderWithIntl(<>{tourScenes("developer")}</>);
    expect(dev.container.textContent).toContain("Need you");
    expect(dev.container.textContent).toContain("Certificate of authorship");
    expect(dev.container.textContent).toContain("Your turn");
    dev.unmount();
    const org = renderWithIntl(<>{tourScenes("org")}</>);
    expect(org.container.textContent).toContain("New");
    expect(org.container.textContent).toContain("Confidential");
    expect(org.container.textContent).toContain("Who has seen this");
  });
});
