import { cleanup, render, screen, within } from "@testing-library/react";
import Link from "next/link";
import { afterEach, describe, expect, it } from "vitest";

import { PageHero } from "./PageHero";

afterEach(cleanup);

// D-67 (P25; REQ-UX-01, REQ-UX-02): one page language for list and home screens: a mono eyebrow saying where you are,
// one h1, a one-sentence lead, the screen's one primary action, an optional aside and the page's tabs.
describe("PageHero", () => {
  it("has one h1 under the eyebrow, the lead and the one primary action", () => {
    render(
      <main>
        <PageHero
          eyebrow="Developer / Discover"
          title="Problems worth solving"
          lead="Problems people raise in your niches, newest first."
          action={
            <Link href="/dev/ideas/new" data-primary="" className="btn btn-primary">
              New proposal
            </Link>
          }
        />
      </main>,
    );
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0].textContent).toBe("Problems worth solving");
    const eyebrow = screen.getByText("Developer / Discover");
    expect(eyebrow.className).toContain("page-eyebrow");
    // The eyebrow comes first and is not a heading (it says where you are; the h1 names the page).
    expect(eyebrow.tagName).toBe("P");
    expect(eyebrow.compareDocumentPosition(headings[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/newest first/).className).toContain("page-hero-lead");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "New proposal" })).toBeTruthy();
  });

  it("is a container (it stacks in a narrow column whatever the window) with the title balanced", () => {
    const { container } = render(<PageHero eyebrow="Organisation / Inbox" title="Inbox" />);
    const hero = container.querySelector("[data-page-hero]")!;
    expect(hero.className).toContain("page-hero");
    expect(screen.getByRole("heading", { level: 1 }).className).toContain("page-hero-title");
    expect(container.querySelector("[data-page-hero-aside]")).toBeNull();
  });

  it("holds an aside and the page's tabs after the title", () => {
    render(
      <PageHero
        eyebrow="Developer / My ideas"
        title="My ideas"
        aside={<p>3 published</p>}
        tabs={
          <nav aria-label="Lists">
            <Link href="/dev/ideas">All</Link>
          </nav>
        }
      />,
    );
    const title = screen.getByRole("heading", { level: 1 });
    const tabs = screen.getByRole("navigation", { name: "Lists" });
    expect(title.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(document.querySelector("[data-page-hero-aside]") as HTMLElement).getByText("3 published")).toBeTruthy();
  });

  it("lets a step move focus to its title without a ring", () => {
    render(<PageHero eyebrow="Developer / My ideas" title="My ideas" focusable titleId="ideas-title" />);
    const title = screen.getByRole("heading", { level: 1 });
    expect(title.getAttribute("tabindex")).toBe("-1");
    expect(title.id).toBe("ideas-title");
  });
});
