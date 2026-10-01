import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";
import { EmptyStateFrame } from "./EmptyStateFrame";

afterEach(cleanup);

// docs/spec/07 item 4, AC-UX-5: every empty state is exactly one sentence and one action.
describe("EmptyState", () => {
  it("is one sentence and one link, marked data-empty-state", () => {
    const { container } = render(
      <EmptyState sentence="No engagements yet." action="Go to My ideas" href="/dev/ideas" />,
    );
    const box = container.querySelector("[data-empty-state]")!;
    expect(box.querySelectorAll("p")).toHaveLength(1);
    expect(box.querySelectorAll("a")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Go to My ideas" }).getAttribute("href")).toBe("/dev/ideas");
    expect(box.className.split(" ")).toEqual(expect.arrayContaining(["border-t", "border-line", "pt-6"]));
    expect(box.querySelector("[data-primary]")).toBeNull();
  });

  it("makes the action the screen's primary button when asked", () => {
    render(<EmptyState sentence="No ideas yet." action="New idea" href="/dev/ideas/new" primary />);
    const link = screen.getByRole("link", { name: "New idea" });
    expect(link.hasAttribute("data-primary")).toBe(true);
    expect(link.className).toContain("bg-accent");
  });

  it("drops its hairline where a line is already there, and passes data attributes through", () => {
    const { container } = render(
      <EmptyState sentence="No documents yet." action="Back to the tracker" href="/x" rule={false} data-refusal="mfaSetup" />,
    );
    const box = container.querySelector("[data-empty-state]")!;
    expect(box.getAttribute("data-refusal")).toBe("mfaSetup");
    expect(box.className).not.toMatch(/\bborder-t\b/);
  });
});

describe("EmptyStateFrame", () => {
  it("takes a button as its one action (a form step's empty state)", () => {
    const { container } = render(
      <EmptyStateFrame sentence="No problems match." action={<button type="button">Describe it instead</button>} />,
    );
    const box = container.querySelector("[data-empty-state]")!;
    expect(box.querySelectorAll("p")).toHaveLength(1);
    expect(box.querySelectorAll("button, a")).toHaveLength(1);
  });
});
