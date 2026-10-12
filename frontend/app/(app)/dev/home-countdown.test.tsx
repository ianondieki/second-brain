import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Summary } from "@/components/tracker/model";
import type { Me } from "@/lib/auth/routing";
import { summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { HomeContent } from "./HomeContent";
import { NeedsYouHero } from "./NeedsYouHero";

// P23-3 (REQ-TRACK-03, REQ-DEV-01): Home's "Next deadline" tile says the time left in days, hours and minutes as its
// meta line (the business days in its title); the "Needs you" card and the other engagements' rows show the live clock
// (P26); all count from the page's app-clock instant (X-App-Now) and fall back to the business days when the API sends
// no instant.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));

const NOW = "2026-10-10T06:36:00.000Z";
// The end of 16 Oct 2026 in Nairobi: 6 d 14 h 23 m (and a fraction of a second) after NOW.
const DUE = { due_on: "2026-10-16", business_days_left: 4, overdue: false, due_at: "2026-10-16T20:59:59.999Z" };
const ME = { user: { display_name: "Amina" }, mfa: { enrolled: true, required: false, verified: true } } as unknown as Me;

const mine = (over: Partial<Summary> = {}) =>
  summary({ id: "0199b000-0000-7000-8000-00000000e00a", state: "NDA_PENDING", whose_turn: ["developer"], due: DUE as Summary["due"], ...over });

async function home(engagements: Summary[]) {
  const tree = await HomeContent({ me: ME, engagements, ideas: [], recommended: { kind: "unavailable" }, now: NOW });
  return renderWithIntl(<>{await resolveServerTree(tree)}</>);
}

const tile = () => document.querySelector<HTMLElement>("[data-stat='deadline']")!;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance", "Date"] });
  vi.setSystemTime(new Date("2030-01-01T00:00:00Z")); // the browser's clock, wrong: never read
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Home's Next deadline tile", () => {
  it("says the time left as its meta line, the business days in its title", async () => {
    await home([mine()]);
    expect(tile().textContent).toBe("Next deadline16 Octin 6 days 14 h 23 min");
    expect(tile().getAttribute("title")).toBe("in 4 business days");
    expect(tile().querySelector("time")?.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(tile().querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect(tile().querySelector("[aria-live]")).toBeNull();
  });

  it("keeps the business days when the API sends no instant, and Overdue once overdue", async () => {
    await home([mine({ due: { due_on: "2026-10-16", business_days_left: 4, overdue: false } })]);
    expect(tile().textContent).toBe("Next deadline16 Octin 4 business days");
    expect(tile().getAttribute("title")).toBeNull();
    cleanup();
    await home([mine({ due: { ...DUE, business_days_left: -1, overdue: true } as Summary["due"] })]);
    expect(tile().textContent).toBe("Next deadline16 OctOverdue");
    expect(tile().querySelector("time")).toBeNull();
  });
});

describe("Home's Needs you card", () => {
  // P26: the deadline beside the way in is the live clock (days, hours, minutes in the figure face), the business days
  // and the date as its line; the date figure with its business days stays only without an instant or once overdue.
  it("shows the live clock, the business days and the date as its line; its chips stay two", () => {
    renderWithIntl(<NeedsYouHero item={mine()} href="/dev/engagements/x" action="Open the tracker" now={NOW} />);
    const clock = document.querySelector<HTMLElement>("[data-deadline-clock='lg']")!;
    expect(clock.querySelector("time")?.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(clock.querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect([...clock.querySelectorAll("[data-figure]")].map((figure) => figure.textContent)).toEqual(["6", "14", "23"]);
    expect(clock.querySelector("[data-due]")?.textContent).toBe("4 business days left, due 16 Oct 2026");
    expect(clock.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("open");
    expect(document.querySelector("[aria-live]")).toBeNull();
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(2);
  });

  it("takes the warm look under 24 hours, the step being the developer's", () => {
    renderWithIntl(<NeedsYouHero item={mine()} href="/dev/engagements/x" action="Open the tracker" now="2026-10-16T08:00:00.000Z" />);
    expect(document.querySelector("[data-clock='warm'] [data-clock-figures]")?.textContent).toBe("12 h 59 min");
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(2);
  });

  it("keeps the date as its figure with the business days without an instant, and Overdue once overdue", () => {
    renderWithIntl(<NeedsYouHero item={mine({ due: { due_on: "2026-10-16", business_days_left: 4, overdue: false } })} href="/x" action="Open the tracker" now={NOW} />);
    expect(document.querySelector("[data-deadline-clock]")).toBeNull();
    expect(document.querySelector("[data-due='open']")?.textContent).toBe("16 Octin 4 business days");
    cleanup();
    renderWithIntl(<NeedsYouHero item={mine({ due: { ...DUE, business_days_left: -1, overdue: true } as Summary["due"] })} href="/x" action="Open the tracker" now={NOW} />);
    expect(document.querySelector("[data-deadline-clock]")).toBeNull();
    expect(document.querySelector("[data-due='overdue']")?.textContent).toBe("16 OctOverdue");
  });
});

describe("Home's other engagements", () => {
  // P26: each row waiting on the organisation shows the small live clock, gated as the cards are (words when overdue,
  // on hold, ended, or without the API's instant).
  it("shows the small live clock on an open row and keeps the words on an overdue one", async () => {
    const other = (id: string, due: Summary["due"]) => mine({ id, whose_turn: ["org"], due });
    await home([
      other("0199b000-0000-7000-8000-00000000e0a1", DUE as Summary["due"]),
      other("0199b000-0000-7000-8000-00000000e0a2", { ...DUE, business_days_left: -1, overdue: true } as Summary["due"]),
    ]);
    const rows = document.querySelector("[data-home='others']")!;
    const open = rows.querySelector("[data-engagement='0199b000-0000-7000-8000-00000000e0a1']")!;
    expect(open.querySelector("[data-deadline-clock='sm'] time")?.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect([...open.querySelectorAll("[data-figure]")].map((figure) => figure.textContent)).toEqual(["6", "14", "23"]);
    expect(open.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("open");
    const late = rows.querySelector("[data-engagement='0199b000-0000-7000-8000-00000000e0a2']")!;
    expect(late.querySelector("[data-deadline-clock]")).toBeNull();
    expect(late.querySelector("[data-due='overdue']")?.textContent).toBe("Overdue by 1 business day, was due 16 Oct 2026");
  });
});
