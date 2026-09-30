import { cleanup, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ComponentType } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { AlertIcon, CheckIcon, ClockIcon, Icon, InfoIcon, LockIcon, SendIcon, type IconProps } from "./status-icons";

afterEach(cleanup);

const STATUS_ICONS: Record<string, ComponentType<IconProps>> = {
  AlertIcon,
  CheckIcon,
  InfoIcon,
  LockIcon,
  ClockIcon,
  SendIcon,
};

function svgOf(Drawn: ComponentType<IconProps>, props: IconProps = {}) {
  return render(<Drawn {...props} />).container.querySelector("svg")!;
}

// docs/spec/07 item 6: status is icon + text + colour; the icon is decoration, the words carry the meaning.
describe("status icons", () => {
  it("draw on the shared 20 px grid in the text colour, hidden from assistive tech and never focusable", () => {
    for (const [name, Drawn] of Object.entries(STATUS_ICONS)) {
      const svg = svgOf(Drawn);
      const attributes = ["width", "height", "viewBox", "fill", "stroke", "stroke-width", "aria-hidden", "focusable"];
      expect(attributes.map((a) => svg.getAttribute(a)), name).toEqual([
        "20",
        "20",
        "0 0 20 20",
        "none",
        "currentColor",
        "1.75",
        "true",
        "false",
      ]);
      expect(svg.children.length, name).toBeGreaterThan(0);
      cleanup();
    }
  });

  it("are each a different drawing", () => {
    const drawings = Object.values(STATUS_ICONS).map((Drawn) => {
      const markup = svgOf(Drawn).innerHTML;
      cleanup();
      return markup;
    });
    expect(new Set(drawings).size).toBe(drawings.length);
  });

  it("take the caller's size, colour and attributes over the defaults", () => {
    const svg = svgOf(CheckIcon, { className: "size-5 text-ok", strokeWidth: 2, "data-mark": "ok" } as IconProps);
    expect(svg.getAttribute("class")).toBe("size-5 text-ok");
    expect(svg.getAttribute("stroke-width")).toBe("2");
    expect(svg.getAttribute("data-mark")).toBe("ok");
  });

  it("let a drawn mark stand alone with a name when a caller needs one", () => {
    const svg = svgOf(Icon, { role: "img", "aria-hidden": false, "aria-label": "Confidential" });
    expect([svg.getAttribute("role"), svg.getAttribute("aria-hidden"), svg.getAttribute("aria-label")]).toEqual([
      "img",
      "false",
      "Confidential",
    ]);
  });

  it("stay a module client components can import cheaply: React types only, no next/* or other icons", () => {
    const source = readFileSync(join(__dirname, "status-icons.tsx"), "utf-8");
    const imports = source.match(/^import .*$/gm) ?? [];
    expect(imports).toEqual(['import type { SVGProps } from "react";']);
  });
});
