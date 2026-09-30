import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const status = vi.hoisted(() => ({ pending: false }));
vi.mock("next/link", () => ({ useLinkStatus: () => ({ pending: status.pending }) }));

import { LinkPending } from "./LinkPending";

afterEach(cleanup);

// P16-B fix round 1: in-app navigation feedback is a fixed-size hint whose opacity follows the link's pending state.
describe("LinkPending", () => {
  it("is always rendered, hidden from assistive tech, and invisible while nothing is pending", () => {
    status.pending = false;
    const { container } = render(<LinkPending />);
    const hint = container.firstElementChild!;
    expect(hint.getAttribute("aria-hidden")).toBe("true");
    expect(hint.getAttribute("data-link-pending")).toBe("false");
    expect(hint.className.split(" ")).toEqual(expect.arrayContaining(["opacity-0", "h-[3px]", "w-6"]));
    expect(hint.className).not.toContain("animate-pulse");
  });

  it("shows in the accent colour while the tapped link's page is on its way, pulsing only without reduced motion", () => {
    status.pending = true;
    const { container } = render(<LinkPending />);
    const hint = container.firstElementChild!;
    expect(hint.getAttribute("data-link-pending")).toBe("true");
    const classes = hint.className.split(" ");
    expect(classes).toEqual(expect.arrayContaining(["opacity-100", "bg-jacaranda", "motion-safe:animate-pulse"]));
    expect(classes).not.toContain("opacity-0");
    // Same box in both states: no layout shift.
    expect(classes).toEqual(expect.arrayContaining(["h-[3px]", "w-6"]));
  });
});
