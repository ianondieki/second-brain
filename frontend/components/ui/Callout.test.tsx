import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Alert } from "./Alert";
import { Callout } from "./Callout";
import { noticeTone } from "./notice";

afterEach(cleanup);

// P16 design system, Notices: Callout (static) and Alert (announced) share one look: a 1 px tone border, the tone's
// wash, an icon and words, rounded-control. No coloured left rule.
describe("Callout", () => {
  it("is static: no live role, so nothing is announced when the page loads", () => {
    const { container } = render(<Callout tone="info">Verification usually takes 2 business days.</Callout>);
    const box = container.firstElementChild!;
    expect(box.getAttribute("role")).toBeNull();
    expect(box.getAttribute("aria-live")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each(["error", "info", "ok", "neutral"] as const)("draws the %s tone as a 1 px border and a wash", (tone) => {
    const { container } = render(<Callout tone={tone}>Words</Callout>);
    const classes = container.firstElementChild!.className.split(" ");
    expect(classes).toEqual(expect.arrayContaining(["border", "rounded-control", ...noticeTone[tone].split(" ")]));
    expect(classes.some((c) => /^border-l-/.test(c))).toBe(false);
    expect(container.querySelector("svg[aria-hidden='true']")).not.toBeNull();
  });

  it("shows a title above the words and can name its region by it", () => {
    render(
      <Callout as="section" tone="info" title="Your turn" titleId="whose" aria-labelledby="whose" titleSize="lg">
        Sign the NDA.
      </Callout>,
    );
    const region = screen.getByRole("region", { name: "Your turn" });
    expect(region.tagName).toBe("SECTION");
    expect(screen.getByText("Your turn").className).toContain("text-lg");
    expect(region.textContent).toBe("Your turnSign the NDA.");
  });

  it("takes a drawn mark in place of the tone's icon", () => {
    const { container } = render(
      <Callout tone="neutral" icon={<svg data-mark="current" aria-hidden="true" />}>
        Words
      </Callout>,
    );
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    expect(container.querySelector("svg[data-mark='current']")).not.toBeNull();
  });
});

describe("Alert", () => {
  it.each([
    ["error", "alert"],
    ["info", "status"],
    ["ok", "status"],
  ] as const)("shares the Callout's %s tone and is announced as %s", (tone, role) => {
    render(<Alert tone={tone}>Saved.</Alert>);
    const alert = screen.getByRole(role);
    expect(alert.className.split(" ")).toEqual(expect.arrayContaining(noticeTone[tone].split(" ")));
  });
});
