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
// meta line (the business days in its title), and the "Needs you" card says it under its date; both count from the
// page's app-clock instant (X-App-Now) and fall back to the business days when the API sends no instant.

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
    expect(tile().textContent).toBe("Next deadline16 Oct6 d 14 h 23 m left");
    expect(tile().getAttribute("title")).toBe("in 4 business days");
    expect(tile().querySelector("time")?.getAttribute("dateTime")).toBe(DUE.due_at);
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
  it("says the time left under its date, quiet, then the business days; its chips stay two", () => {
    renderWithIntl(<NeedsYouHero item={mine()} href="/dev/engagements/x" action="Open the tracker" now={NOW} />);
    const timer = document.querySelector<HTMLElement>("[data-timer]")!;
    expect(timer.textContent).toBe("6 d 14 h 23 m left");
    expect(timer.className).toContain("text-sm");
    expect(timer.className).toContain("text-ink-soft");
    const when = timer.closest("[data-due]")!;
    expect(when.querySelector("time")?.textContent).toBe("16 Oct");
    expect(when.textContent).toBe("16 Oct6 d 14 h 23 m leftin 4 business days");
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(2);
  });

  it("takes the warm mark under 24 hours, the step being the developer's", () => {
    renderWithIntl(<NeedsYouHero item={mine()} href="/dev/engagements/x" action="Open the tracker" now="2026-10-16T08:00:00.000Z" />);
    expect(document.querySelector("[data-timer='warm']")?.textContent).toBe("12 h 59 m left");
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(2);
  });
});
