import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { buttonClass } from "./Button";
import { ButtonLink } from "./ButtonLink";

afterEach(cleanup);

// A navigation that looks like a button. Its pending hint's tone and size are pending-links.test.tsx's.
describe("ButtonLink", () => {
  it("is a secondary button look by default and is not the screen's primary action", () => {
    render(<ButtonLink href="/dev/ideas/1/edit">Edit idea</ButtonLink>);
    const link = screen.getByRole("link", { name: "Edit idea" });
    expect(link.getAttribute("href")).toBe("/dev/ideas/1/edit");
    expect(link.className).toBe(buttonClass("secondary", "relative"));
    expect(link.hasAttribute("data-primary")).toBe(false);
  });

  it("marks the primary variant as the screen's one primary action, keeping the caller's classes", () => {
    render(
      <ButtonLink href="/signup" variant="primary" className="mt-6" aria-describedby="why">
        Create an account
      </ButtonLink>,
    );
    const link = screen.getByRole("link", { name: "Create an account" });
    expect(link.hasAttribute("data-primary")).toBe(true);
    expect(link.className).toBe(buttonClass("primary", "relative mt-6"));
    expect(link.getAttribute("aria-describedby")).toBe("why");
  });

  it("keeps next/link out of the plain Button's module, so client buttons do not bundle it", () => {
    const button = readFileSync(join(__dirname, "Button.tsx"), "utf-8");
    expect(button).not.toMatch(/from "next\/link"/);
  });
});
