import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Badge } from "./Badge";
import { CheckIcon } from "./status-icons";

afterEach(cleanup);

// P16 design system, Status: icon + words + tone, the same everywhere; never colour alone (docs/spec/07 item 6).
describe("Badge", () => {
  it.each([
    ["accent", "text-jacaranda"],
    ["ok", "text-ok"],
    ["error", "text-error"],
    ["neutral", "text-ink-soft"],
  ] as const)("carries the %s tone in its colour, with the words", (tone, colour) => {
    render(<Badge tone={tone}>Published</Badge>);
    const badge = screen.getByText("Published").parentElement!;
    expect(badge.className.split(" ")).toContain(colour);
    expect(badge.textContent).toBe("Published");
  });

  it("puts a decorative icon before the words, so the words are what is read", () => {
    const { container } = render(
      <Badge tone="ok" icon={<CheckIcon />}>
        Published
      </Badge>,
    );
    const badge = container.firstElementChild!;
    expect(badge.firstElementChild?.tagName.toLowerCase()).toBe("svg");
    expect(badge.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
    expect(badge.textContent).toBe("Published");
  });

  it("is filled and fully rounded only when solid (the one 'Your turn' marker)", () => {
    const { container, rerender } = render(<Badge tone="accent">Your turn</Badge>);
    expect(container.firstElementChild!.className).not.toMatch(/\bbg-|rounded-full/);
    rerender(
      <Badge tone="accent" solid>
        Your turn
      </Badge>,
    );
    const classes = container.firstElementChild!.className.split(" ");
    expect(classes).toEqual(expect.arrayContaining(["bg-jacaranda", "text-on-accent", "rounded-full"]));
    expect(classes).not.toContain("text-jacaranda");
  });

  it("passes data-chip and data-badge through, so tests can count a card's chips", () => {
    const { container } = render(
      <>
        <Badge data-chip="turn">Your turn</Badge>
        <Badge data-badge="e2">Verified</Badge>
      </>,
    );
    expect(container.querySelector("[data-chip='turn']")?.textContent).toBe("Your turn");
    expect(container.querySelector("[data-badge='e2']")?.textContent).toBe("Verified");
  });
});
