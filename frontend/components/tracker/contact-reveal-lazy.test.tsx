import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { LazyContactReveal } from "./lazy";

// P27 UX (docs/spec/07 item 5; the organisation's tracker was 694 B over its 150 KB by this chunk): the named
// contact's reveal is a plain button in the page's HTML; its chunk is fetched when the pointer reaches the button or
// it takes focus, and only pressing it draws the part, which reveals at once.

const loaded = vi.hoisted(() => ({ count: 0 }));
vi.mock("./ContactReveal", () => {
  loaded.count += 1;
  return {
    ContactReveal: ({ engagementId, start }: { engagementId: string; start?: boolean }) => (
      <p data-part-drawn={engagementId}>{start ? "started" : "waiting"}</p>
    ),
  };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
afterEach(cleanup);

describe("the contact reveal on the tracker", () => {
  it("is a button until pressed, its chunk fetched on hover or focus; the press draws the part, which starts", async () => {
    const { container } = renderWithIntl(<LazyContactReveal engagementId="e1" />);
    const button = screen.getByRole("button", { name: en.trackerActions.contact.reveal });
    expect(button.getAttribute("data-opens")).toBe("contact");
    expect(button.hasAttribute("data-primary")).toBe(false);
    expect(loaded.count).toBe(0);
    expect(container.querySelector("[data-part-drawn]")).toBeNull();
    await act(async () => fireEvent.pointerEnter(button));
    expect(loaded.count).toBe(1); // fetched, not drawn
    expect(container.querySelector("[data-part-drawn]")).toBeNull();
    await act(async () => fireEvent.click(button));
    expect((await screen.findByText("started")).getAttribute("data-part-drawn")).toBe("e1");
    expect(screen.queryByRole("button", { name: en.trackerActions.contact.reveal })).toBeNull();
  });
});
