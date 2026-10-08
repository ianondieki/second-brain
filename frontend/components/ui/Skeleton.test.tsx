import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Skeleton, SkeletonCards, SkeletonHero, SkeletonScreen } from "./Skeleton";

afterEach(cleanup);

// D-67 (P25): skeletons shaped like the page to come; decorative, with one "Loading" for assistive technology; their
// sweep stands still under reduced motion (app/globals-p25.test.ts).
describe("Skeleton", () => {
  it("is decorative", () => {
    const { container } = render(<Skeleton className="h-4 w-20" />);
    const block = container.querySelector("[data-skeleton]")!;
    expect(block.getAttribute("aria-hidden")).toBe("true");
    expect(block.className).toContain("skeleton");
  });

  it("has PageHero's shape (eyebrow, title, lead, the action's pill, tabs) and a card grid's", () => {
    const { container } = render(
      <>
        <SkeletonHero tabs />
        <SkeletonCards count={2} band />
      </>,
    );
    const hero = container.querySelector("[data-skeleton-hero]")!;
    expect(hero.className).toContain("page-hero");
    expect(hero.querySelectorAll("[data-skeleton]").length).toBe(4 + 3);
    const cards = container.querySelector("[data-skeleton-cards]")!;
    expect(cards.className).toContain("card-grid");
    expect(cards.children).toHaveLength(2);
  });

  it("says Loading once, politely, on a loading screen", () => {
    render(
      <SkeletonScreen label="Loading Discover">
        <SkeletonHero />
      </SkeletonScreen>,
    );
    expect(screen.getByRole("status").textContent).toBe("Loading Discover");
    expect(screen.getByRole("status").parentElement!.getAttribute("aria-busy")).toBe("true");
  });
});
