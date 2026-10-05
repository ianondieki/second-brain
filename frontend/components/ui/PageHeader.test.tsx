import { cleanup, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { BackLink } from "./BackLink";
import { PageHeader } from "./PageHeader";

afterEach(cleanup);

// P16 design system, Page header: optional back link, the page's one h1 at one size, a one-sentence lead, and the
// primary action's slot.
describe("PageHeader", () => {
  it("renders the page's one h1 with the title recipe, and its lead", () => {
    render(<PageHeader title="My ideas" lead="Draft, publish and pitch your ideas." />);
    const h1 = screen.getByRole("heading", { level: 1, name: "My ideas" });
    expect(h1.className.split(" ")).toEqual(expect.arrayContaining(["text-2xl", "lg:text-3xl", "text-ink"]));
    expect(h1.hasAttribute("tabindex")).toBe(false);
    expect(screen.getByText("Draft, publish and pitch your ideas.").tagName).toBe("P");
    expect(document.querySelectorAll("h1")).toHaveLength(1);
  });

  it("puts the back link above the title, as its own 44 px line", () => {
    render(<PageHeader title="Cold chain" back={{ href: "/dev/ideas", label: "All ideas" }} />);
    const link = screen.getByRole("link", { name: "All ideas" });
    expect(link.getAttribute("href")).toBe("/dev/ideas");
    expect(link.className).toContain("min-h-11");
    expect(link.compareDocumentPosition(screen.getByRole("heading", { level: 1 })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("holds the primary action in its slot", () => {
    render(
      <PageHeader
        title="My ideas"
        action={
          <button type="button" data-primary="">
            New idea
          </button>
        }
      />,
    );
    expect(document.querySelectorAll("header [data-primary]")).toHaveLength(1);
  });

  it("lets a step move focus to the title without drawing a ring on it", () => {
    const ref = createRef<HTMLHeadingElement>();
    render(<PageHeader title="Pitch sent" titleRef={ref} titleId="page-title" focusable />);
    expect(ref.current?.id).toBe("page-title");
    expect(ref.current?.getAttribute("tabindex")).toBe("-1");
    expect(ref.current?.className).toContain("focus:outline-none");
  });
});

describe("BackLink", () => {
  it("is a standalone link in its own paragraph", () => {
    render(<BackLink href="/org/engagements">All engagements</BackLink>);
    const link = screen.getByRole("link", { name: "All engagements" });
    expect(link.parentElement?.tagName).toBe("P");
    expect(link.parentElement?.className).toBe("-mt-2 mb-4");
  });

  it("takes a class and data attributes for a page that hides it while a notice carries the way on", () => {
    render(
      <BackLink href="/billing" className="[main:has([data-checkout-blocked])_&]:hidden" data-page-back="">
        Plan and billing
      </BackLink>,
    );
    const line = screen.getByRole("link", { name: "Plan and billing" }).parentElement!;
    expect(line.getAttribute("data-page-back")).toBe("");
    expect(line.className).toBe("-mt-2 mb-4 [main:has([data-checkout-blocked])_&]:hidden");
  });
});
