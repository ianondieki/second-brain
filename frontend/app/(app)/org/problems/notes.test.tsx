import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PostedNote, StateNote } from "./Notes";

// REQ-DIR-05, ux-review MAJOR 3 (WCAG 2.4.3, 4.1.3): after posting, the "sent for review" note arrives in a live region
// and takes focus; after Close is confirmed (its button is gone), the Brief's closed note takes focus.

afterEach(cleanup);

describe("the posted note", () => {
  it("is a status that takes focus once the page runs, then leaves the address so a reload does not repeat it", () => {
    window.history.replaceState(null, "", "/org/problems?org=01a0ee62-0000-7000-8000-00000000000a&posted=1#top");
    render(<PostedNote text="Brief sent for review." />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Brief sent for review.");
    expect(document.activeElement).toBe(status);
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/org/problems?org=01a0ee62-0000-7000-8000-00000000000a#top",
    );
    expect(screen.getByRole("status")).toBe(status); // still shown: no refetch, no shift
  });
});

describe("the state note", () => {
  it("takes focus when the state it shows changes, never on the first load", () => {
    const { rerender } = render(
      <StateNote state="published">
        <p>Developers see this Brief on Discover.</p>
      </StateNote>,
    );
    const box = document.querySelector<HTMLElement>("[data-state-focus]")!;
    expect(box.getAttribute("role")).toBe("status");
    expect(box.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).not.toBe(box);
    rerender(
      <StateNote state="closed">
        <p>This Brief is closed.</p>
      </StateNote>,
    );
    expect(document.activeElement).toBe(box);
    expect(box.textContent).toBe("This Brief is closed.");
  });
});
