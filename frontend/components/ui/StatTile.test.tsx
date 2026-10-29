import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProgressBar } from "./ProgressBar";
import { Sparkline } from "./Sparkline";
import { StatTile } from "./StatTile";

afterEach(cleanup);

describe("StatTile", () => {
  it("shows the label, the figure and the meta line; a link when it has somewhere to go", () => {
    render(<StatTile label="Ideas" value={3} meta="1 draft" href="/dev/ideas" data-stat="ideas" />);
    const tile = screen.getByRole("link");
    expect(tile.getAttribute("href")).toBe("/dev/ideas");
    expect(tile.textContent).toBe("Ideas31 draft");
    expect(tile.querySelector("[data-sparkline]")).toBeNull();
  });

  it("draws a sparkline only for a series of two or more points, decorative", () => {
    const { container } = render(
      <>
        <StatTile label="Views" value={12} spark={[1, 4, 2, 12]} />
        <StatTile label="One" value={1} spark={[1]} />
      </>,
    );
    const sparks = container.querySelectorAll("[data-sparkline]");
    expect(sparks).toHaveLength(1);
    expect(sparks[0].getAttribute("aria-hidden")).toBe("true");
    expect(sparks[0].querySelector("path")?.getAttribute("stroke-width")).toBe("2");
  });
});

describe("Sparkline", () => {
  it("spans the box from the lowest to the highest value", () => {
    const { container } = render(<Sparkline values={[0, 10]} />);
    const d = container.querySelector("path")!.getAttribute("d")!;
    expect(d).toMatch(/^M3\.0 25\.0 L93\.0 3\.0$/);
  });
});

describe("ProgressBar", () => {
  it("is a progressbar with its value, segmented for a handful of steps", () => {
    const { container } = render(<ProgressBar value={2} max={5} label="Stage 3 of 5: Agreement" />);
    const bar = screen.getByRole("progressbar", { name: "Stage 3 of 5: Agreement" });
    expect(bar.getAttribute("aria-valuenow")).toBe("2");
    expect(bar.getAttribute("aria-valuemax")).toBe("5");
    expect(container.querySelectorAll("[data-progress] > span")).toHaveLength(5);
    expect([...container.querySelectorAll("[data-progress] > span")].filter((s) => s.className.includes("bg-accent"))).toHaveLength(2);
  });

  it("clamps a value past the end", () => {
    render(<ProgressBar value={9} max={5} label="Done" />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("5");
  });
});
