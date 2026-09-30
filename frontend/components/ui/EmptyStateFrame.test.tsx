import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { EmptyStateFrame } from "./EmptyStateFrame";

afterEach(cleanup);

// docs/spec/07 item 4, AC-UX-5: an empty or closed state is exactly one sentence and one action.
describe("EmptyStateFrame", () => {
  it("holds one sentence and one action, under a hairline by default", () => {
    const { container } = render(
      <EmptyStateFrame
        sentence="No scout has run yet."
        action={
          <button type="button" data-primary="">
            Set up a scout
          </button>
        }
      />,
    );
    const frame = container.firstElementChild!;
    expect(frame.hasAttribute("data-empty-state")).toBe(true);
    expect(frame.querySelectorAll("p")).toHaveLength(1);
    expect(frame.querySelector("p")!.textContent).toBe("No scout has run yet.");
    expect(screen.getByRole("button", { name: "Set up a scout" })).toBeTruthy();
    expect(frame.className.split(" ")).toEqual(expect.arrayContaining(["border-t", "border-line", "pt-6"]));
  });

  it("drops the hairline where a line is already there, and carries data attributes and classes", () => {
    const { container } = render(
      <EmptyStateFrame
        sentence="This pitch is closed."
        action={<button type="button">Pitch it again</button>}
        rule={false}
        className="mt-2"
        data-refusal="closed"
      />,
    );
    const frame = container.firstElementChild!;
    expect(frame.className).not.toContain("border-t");
    expect(frame.className.split(" ")).toContain("mt-2");
    expect(frame.getAttribute("data-refusal")).toBe("closed");
    expect(frame.hasAttribute("data-empty-state")).toBe(true);
  });

  it("does not import next/link, so a client component whose action is a button does not bundle it", () => {
    expect(readFileSync(join(__dirname, "EmptyStateFrame.tsx"), "utf-8")).not.toMatch(/from "next\/link"/);
  });
});
