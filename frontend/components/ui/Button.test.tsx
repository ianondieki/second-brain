import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "tailwindcss";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button, buttonClass } from "./Button";

const GLOBALS = join(dirname(fileURLToPath(import.meta.url)), "../../app/globals.css");
const require = createRequire(import.meta.url);

/** The CSS Tailwind generates for these classes with the app's theme (app/globals.css), as `next build` does. */
async function cssFor(classes: string): Promise<string> {
  const { build } = await compile(await readFile(GLOBALS, "utf8"), {
    base: dirname(GLOBALS),
    loadStylesheet: async (id, base) => {
      const path = require.resolve(id === "tailwindcss" ? "tailwindcss/index.css" : id, { paths: [base] });
      return { path, base: dirname(path), content: await readFile(path, "utf8") };
    },
  });
  return build(classes.split(/\s+/).filter(Boolean));
}

/** The declarations of every generated rule whose selector ends with `suffix` (Tailwind's output has no nesting). */
function declarationsEndingWith(css: string, suffix: string): string[] {
  const found: string[] = [];
  for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (selector.trim().endsWith(suffix)) found.push(...body.split(";").map((d) => d.trim()).filter(Boolean));
  }
  return found;
}

/** WCAG 2.2 contrast ratio of two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

afterEach(cleanup);

describe("Button busy", () => {
  it("stays focusable but ignores presses, marked aria-disabled", () => {
    const onClick = vi.fn();
    render(
      <Button variant="link" busy onClick={onClick}>
        Cancel setup
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Cancel setup" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect((button as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("is not marked when idle, and presses go through", () => {
    const onClick = vi.fn();
    render(
      <Button variant="link" onClick={onClick}>
        Cancel setup
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Cancel setup" });
    expect(button.getAttribute("aria-disabled")).toBeNull();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows a busy link as quieter text with a dotted underline and a progress cursor, hover included", async () => {
    const css = await cssFor(buttonClass("link"));
    const busy = declarationsEndingWith(css, '[aria-disabled="true"]');
    expect(busy).toEqual(
      expect.arrayContaining(["cursor: progress", "color: var(--ink-soft)", "text-decoration-style: dotted"]),
    );
    // Hovering a busy link neither brings the accent colour back nor thickens the underline.
    const busyHover = declarationsEndingWith(css, '[aria-disabled="true"]:hover');
    expect(busyHover).toEqual(expect.arrayContaining(["color: var(--ink-soft)", "text-decoration-thickness: 1px"]));
  });

  it("keeps a busy link's text at 4.5:1 or more on the page and on fields", async () => {
    const globals = await readFile(GLOBALS, "utf8");
    const token = (name: string) => globals.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i"))![1];
    expect(contrast(token("ink-soft"), token("paper"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("ink-soft"), token("field"))).toBeGreaterThanOrEqual(4.5);
  });
});

// P16 design system: destructive and ending steps (delete, withdraw, decline) are one Button variant.
describe("Button danger", () => {
  it("is outlined in the error colour, never filled, and never the screen's primary action", async () => {
    render(<Button variant="danger">Withdraw</Button>);
    const button = screen.getByRole("button", { name: "Withdraw" });
    expect(button.hasAttribute("data-primary")).toBe(false);
    const css = await cssFor(buttonClass("danger"));
    // P20: the variants are CSS component classes (globals.css), so the rule is read there.
    const danger = declarationsEndingWith(css, ".btn-danger");
    expect(danger).toEqual(expect.arrayContaining(["color: var(--error)", "border: 1px solid var(--error)", "background: var(--field)"]));
    expect(declarationsEndingWith(css, ".btn-danger:hover")).toContain("background: var(--error-wash)");
    expect(danger.join(";")).not.toMatch(/background: var\(--error\)/);
  });

  it("stays focusable and ignores presses while busy", () => {
    const onClick = vi.fn();
    render(
      <Button variant="danger" busy onClick={onClick}>
        Withdraw
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Withdraw" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});
