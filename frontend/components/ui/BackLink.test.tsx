import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BackLink } from "./BackLink";
import { standaloneLinkClass } from "./Button";

afterEach(cleanup);

describe("BackLink", () => {
  it("is a standalone link back to the list, on its own line above the title, with the pending hint after the words", () => {
    render(<BackLink href="/dev/ideas">All my ideas</BackLink>);
    const link = screen.getByRole("link", { name: "All my ideas" });
    expect(link.getAttribute("href")).toBe("/dev/ideas");
    expect(link.className).toBe(standaloneLinkClass); // its own 44 px band
    const line = link.parentElement!;
    expect(line.tagName).toBe("P");
    expect(line.className.split(" ")).toEqual(["-mt-2", "mb-4"]);
    const hint = link.querySelector("[data-link-pending]")!;
    expect(hint.getAttribute("aria-hidden")).toBe("true");
    expect(hint.className.split(" ")).toContain("ml-2");
    expect(link.lastElementChild).toBe(hint);
  });

  it("puts the caller's class and data attributes on its line, not on the link", () => {
    render(
      <BackLink href="/billing" className="hidden" data-back="checkout">
        Plan &amp; billing
      </BackLink>,
    );
    const link = screen.getByRole("link", { name: "Plan & billing" });
    const line = link.parentElement!;
    expect(line.className.split(" ")).toEqual(["-mt-2", "mb-4", "hidden"]);
    expect(line.getAttribute("data-back")).toBe("checkout");
    expect(link.hasAttribute("data-back")).toBe(false);
  });
});
