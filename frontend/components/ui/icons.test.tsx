import { cleanup, render } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, describe, expect, it } from "vitest";

import * as icons from "./icons";
import * as statusIcons from "./status-icons";
import type { IconProps } from "./status-icons";

afterEach(cleanup);

const ALL = Object.entries(icons) as Array<[string, ComponentType<IconProps>]>;

// One authored icon set (20 px grid, 1.75 stroke, currentColor, decorative): the navigation and status icons that only
// server components draw live here, and the ones client components use are re-exported from status-icons.
describe("the icon set", () => {
  it("re-exports the status icons themselves, so there is one drawing of each", () => {
    for (const name of ["AlertIcon", "CheckIcon", "ClockIcon", "InfoIcon", "LockIcon", "SendIcon"] as const) {
      expect(icons[name], name).toBe(statusIcons[name]);
    }
  });

  it("draws every icon on the shared grid, decorative and in the text colour", () => {
    expect(ALL.length).toBeGreaterThanOrEqual(15);
    for (const [name, Drawn] of ALL) {
      const svg = render(<Drawn className="size-5" />).container.querySelector("svg")!;
      expect(
        [svg.getAttribute("viewBox"), svg.getAttribute("stroke"), svg.getAttribute("aria-hidden")],
        name,
      ).toEqual(["0 0 20 20", "currentColor", "true"]);
      expect(svg.getAttribute("class"), name).toBe("size-5");
      expect(svg.querySelectorAll("path, circle, rect").length, name).toBeGreaterThan(0);
      cleanup();
    }
  });

  it("gives every icon its own drawing", () => {
    const drawings = new Map<string, string>();
    for (const [name, Drawn] of ALL) {
      const markup = render(<Drawn />).container.querySelector("svg")!.innerHTML;
      cleanup();
      expect([...drawings].find(([, other]) => other === markup)?.[0], name).toBeUndefined();
      drawings.set(name, markup);
    }
  });

  it("draws Listed (E0) as an open dashed ring, never a check, so it cannot read as verified", () => {
    const svg = render(<icons.ListedIcon />).container.querySelector("svg")!;
    expect(svg.querySelector("circle")?.getAttribute("stroke-dasharray")).toBeTruthy();
    const check = render(<icons.CheckIcon />).container.querySelector("svg")!;
    const checkPaths = [...check.querySelectorAll("path")].map((p) => p.getAttribute("d"));
    for (const path of svg.querySelectorAll("path")) expect(checkPaths).not.toContain(path.getAttribute("d"));
  });
});
