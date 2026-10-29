import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { PublicActivity } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { Activity } from "./Activity";
import { ago, Ticker } from "./Ticker";

// P24 (REQ-UX-03; D-66): "What's happening". A CSS marquee of the public activity (two copies of the row, the moving
// one hidden from assistive technology), paused on hover and focus, still and scrollable under reduced motion, with a
// visually hidden list read once; left out when the feed cannot be read; "Seeded example" when it is the seed's.

const read = vi.hoisted(() => vi.fn());
vi.mock("@/lib/public/public-data", () => ({ publicActivity: read }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

const FEED: PublicActivity = {
  generated_at: "2026-10-07T07:40:00Z",
  seeded: true,
  items: [
    { id: "a", kind: "version_registered", at: "2026-10-07T07:35:00Z", county: "Kisumu", niche: "Agriculture", title: "Cold chain for dairy co-ops", stage: null, seeded: true },
    { id: "b", kind: "brief_opened", at: "2026-10-05T07:40:00Z", county: "Mombasa", niche: "Logistics", title: null, stage: null, seeded: true },
  ],
};
const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");

describe("Ticker", () => {
  it("moves two copies of the row, hidden from assistive technology, which reads one list", () => {
    const { container } = renderWithIntl(<Ticker activity={FEED} />);
    // Nothing in the moving box takes focus or names itself: it is decorative, the list below is what is read.
    expect(screen.queryByRole("region")).toBeNull();
    expect(container.querySelector(".ticker [tabindex]")).toBeNull();
    const track = container.querySelector<HTMLElement>(".ticker-track")!;
    expect(track.getAttribute("aria-hidden")).toBe("true");
    expect(track.style.getPropertyValue("--ticker-items")).toBe("2");
    expect(track.querySelectorAll(".ticker-row")).toHaveLength(2);
    const list = screen.getByRole("list", { name: "Recent activity" });
    expect(list.className).toContain("sr-only");
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Cold chain for dairy co-ops. Version registered. Kisumu. 5 minutes ago",
      "Brief opened. Mombasa. 2 days ago",
    ]);
    expect(container.querySelectorAll("[data-ticker='page'] .ticker-item")).toHaveLength(4);
  });

  it("pauses on hover and with its Pause button, and stands still, one copy wrapped into rows, under reduced motion", () => {
    expect(css).toMatch(/\.ticker:hover \.ticker-track,\s*\[data-motion\]\[data-paused\] \.ticker-track \{\s*animation-play-state: paused;/);
    const reduced = css.slice(css.lastIndexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/\.ticker-track,/);
    expect(reduced).toMatch(/\.ticker-row \{\s*flex-wrap: wrap;/);
    expect(reduced).toMatch(/\.ticker-row \+ \.ticker-row,\s*\.motion-toggle \{\s*display: none !important;/);
  });

  it("lets a title wrap to two lines and never cuts the kind of event", () => {
    const { container } = renderWithIntl(<Ticker activity={FEED} />);
    const item = container.querySelector(".ticker-item")!;
    expect(item.querySelector(".line-clamp-2")!.textContent).toBe("Cold chain for dairy co-ops");
    expect(item.querySelector(".truncate")).toBeNull();
    expect(item.textContent).toContain("Version registered");
  });

  it("shows Home's three newest as a still list on phones", () => {
    const { container } = renderWithIntl(<Ticker activity={{ ...FEED, items: [...FEED.items, ...FEED.items.map((i) => ({ ...i, id: `${i.id}2` }))] }} variant="strip" />);
    const still = container.querySelector("[data-ticker='strip'] > ul.sm\\:hidden")!;
    expect(still.querySelectorAll(".ticker-item")).toHaveLength(3);
    expect(container.querySelector(".ticker")!.className).toContain("max-sm:hidden");
  });

  it("says how long ago in the page's language", () => {
    expect(ago("en", "2026-10-07T07:39:00Z", "2026-10-07T07:40:00Z")).toBe("1 minute ago");
    expect(ago("en", "2026-10-07T04:40:00Z", "2026-10-07T07:40:00Z")).toBe("3 hours ago");
    expect(ago("en", "2026-10-06T07:40:00Z", "2026-10-07T07:40:00Z")).toBe("yesterday");
    expect(ago("sw", "2026-10-07T04:40:00Z", "2026-10-07T07:40:00Z")).toMatch(/saa/);
  });
});

describe("Activity (the landing's section)", () => {
  it("is labelled Seeded example when the feed is the seed's, with a Pause button for the moving row", async () => {
    read.mockResolvedValue(FEED);
    const { container } = renderWithIntl(<>{await resolveServerTree(<Activity />)}</>);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("What's happening");
    expect(container.querySelector(".demo-label")!.textContent).toBe("Seeded example");
    const pause = screen.getByRole("button", { name: "Pause the activity" });
    expect(pause.closest("[data-motion]")!.contains(container.querySelector(".ticker-track"))).toBe(true);
    expect(screen.getByText(/problems posted, versions registered, Briefs opened\./)).toBeTruthy();
  });

  it("drops the label for a live feed, and is left out when the feed cannot be read", async () => {
    read.mockResolvedValue({ ...FEED, seeded: false });
    const live = renderWithIntl(<>{await resolveServerTree(<Activity />)}</>);
    expect(live.container.querySelector(".demo-label")).toBeNull();
    cleanup();
    read.mockResolvedValue(null);
    const { container } = renderWithIntl(<>{await resolveServerTree(<Activity />)}</>);
    expect(container.innerHTML).toBe("");
  });
});
