import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Section } from "./Section";

afterEach(cleanup);

// P16 design system, Sections: an h2 at 20 px, an optional one-line description and secondary link, and no rule
// under the heading (the rule belongs to a list's rows).
describe("Section", () => {
  it("is a region named by its h2", () => {
    render(
      <Section title="Needs you" description="Engagements waiting on you.">
        <p>Rows</p>
      </Section>,
    );
    const region = screen.getByRole("region", { name: "Needs you" });
    const heading = screen.getByRole("heading", { level: 2, name: "Needs you" });
    expect(heading.className.split(" ")).toContain("text-lg");
    expect(region.textContent).toContain("Engagements waiting on you.");
  });

  it("draws no rule under the heading", () => {
    const { container } = render(<Section title="Contact person">x</Section>);
    const heading = screen.getByRole("heading");
    const lines = [heading, heading.parentElement!, container.querySelector("section")!].map((el) => el.className);
    for (const classes of lines) expect(classes).not.toMatch(/\bborder-(b|t)\b/);
  });

  it("offers one secondary link at the end of the heading row", () => {
    render(
      <Section title="Trending problems" link={{ href: "/dev/discover", label: "See all" }}>
        x
      </Section>,
    );
    const link = screen.getByRole("link", { name: "See all" });
    expect(link.getAttribute("href")).toBe("/dev/discover");
    expect(link.hasAttribute("data-primary")).toBe(false);
    expect(link.parentElement).toBe(screen.getByRole("heading").parentElement);
  });

  it("uses the heading id it is given, or makes one", () => {
    const { rerender } = render(<Section title="History" headingId="history-heading" />);
    expect(screen.getByRole("region", { name: "History" }).getAttribute("aria-labelledby")).toBe("history-heading");
    rerender(<Section title="History" headingLevel={3} />);
    expect(screen.getByRole("heading", { level: 3 }).id).not.toBe("");
  });

  it("can take focus at its heading when a change ends there, without a ring (P16-C1)", () => {
    render(<Section title="Pitches" headingId="pitches-heading" focusable />);
    const heading = screen.getByRole("heading", { level: 2, name: "Pitches" });
    expect(heading.getAttribute("tabindex")).toBe("-1");
    expect(heading.className).toContain("focus:outline-none");
    cleanup();
    render(<Section title="Pitches" />);
    expect(screen.getByRole("heading").hasAttribute("tabindex")).toBe(false);
  });

  it("puts the description before the secondary link in reading order when it has both (P16-C1)", () => {
    const { container } = render(
      <Section title="Repayment nudges" description="Pitched to 2 organisations" link={{ href: "/dev/ideas/1", label: "Open the idea" }} />,
    );
    const order = [...container.querySelectorAll("h2, p, a")].map((el) => el.textContent);
    expect(order).toEqual(["Repayment nudges", "Pitched to 2 organisations", "Open the idea"]);
    expect(screen.getByRole("link", { name: "Open the idea" }).className).toContain("sm:col-start-2");
  });
});
