import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PageSkeleton } from "./PageSkeleton";

afterEach(cleanup);

// P16 design system, Loading: a route's loading state is still wash blocks (header, lead, three rows) with a hidden
// sentence in a status region; no animation, nothing else read out.
describe("PageSkeleton", () => {
  it("says it is loading to screen readers, once", () => {
    renderWithIntl(<PageSkeleton />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Loading this page…");
    expect(screen.getByText("Loading this page…").className).toBe("sr-only");
  });

  it("draws the header, the lead and three rows as hidden, still blocks", () => {
    const { container } = renderWithIntl(<PageSkeleton />);
    const blocks = container.querySelector("[aria-hidden='true']")!;
    expect(blocks.querySelectorAll("li")).toHaveLength(3);
    expect(container.innerHTML).not.toMatch(/animate-|transition/);
  });
});
