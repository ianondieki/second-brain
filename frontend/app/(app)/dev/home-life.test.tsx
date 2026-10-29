import { cleanup, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Summary } from "@/components/tracker/model";
import type { Me } from "@/lib/auth/routing";
import type { PublicActivity } from "@/lib/public/public-data";
import { summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { dayPart } from "./home";
import { HomeContent } from "./HomeContent";

// P24 (REQ-UX-01; D-66): Home with life. The greeting takes the time of day from the app clock in Nairobi; "What's
// happening" sits under the stat tiles, labelled when it is the seed's; the "Your turn" mark on "Needs you" pulses
// (CSS, twice, still under reduced motion).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));

const ME = { user: { display_name: "Amina" }, mfa: { enrolled: true, required: false, verified: true } } as unknown as Me;
const ACTIVITY: PublicActivity = {
  generated_at: "2026-10-07T07:40:00Z",
  seeded: true,
  items: [
    { id: "a", kind: "problem_posted", at: "2026-10-07T07:28:00Z", county: "Nairobi", niche: "ICT", title: "Late diesel deliveries", stage: null, seeded: true },
    { id: "b", kind: "brief_opened", at: "2026-10-07T05:40:00Z", county: null, niche: "Health", title: null, stage: null, seeded: true },
  ],
};

afterEach(cleanup);

async function home(now: string, extra: { activity?: PublicActivity | null; engagements?: Summary[] } = {}) {
  const tree = await HomeContent({ me: ME, engagements: extra.engagements ?? [], ideas: [], recommended: { kind: "unavailable" }, now, activity: extra.activity });
  return renderWithIntl(<>{await resolveServerTree(tree)}</>);
}

describe("Home's greeting", () => {
  it.each([
    ["2026-10-07T01:59:00Z", "evening"], // 04:59 in Nairobi
    ["2026-10-07T02:00:00Z", "morning"], // 05:00
    ["2026-10-07T08:59:00Z", "morning"], // 11:59
    ["2026-10-07T09:00:00Z", "afternoon"], // 12:00
    ["2026-10-07T13:59:00Z", "afternoon"], // 16:59
    ["2026-10-07T14:00:00Z", "evening"], // 17:00
    ["2026-10-07T20:30:00Z", "evening"], // 23:30
  ])("at %s is %s (the hour in Nairobi)", (now, part) => {
    expect(dayPart(now)).toBe(part);
  });

  it("greets by name for the time of day of the app clock", async () => {
    await home("2026-10-07T06:00:00Z");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Good morning, Amina");
    cleanup();
    await home("2026-10-07T15:00:00Z");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Good evening, Amina");
  });
});

describe("Home's What's happening", () => {
  it("sits under the stat tiles, labelled as the seed's, with each item read once", async () => {
    const { container } = await home("2026-10-07T07:40:00Z", { activity: ACTIVITY });
    const section = container.querySelector<HTMLElement>("[data-home='activity']")!;
    expect(container.querySelector("[data-home='stats']")!.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(section).getByRole("heading", { level: 2 }).textContent).toBe("What's happening");
    expect(section.querySelector(".demo-label")!.textContent).toBe("Seeded example");
    const list = within(section).getByRole("list", { name: "Recent activity" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Late diesel deliveries. Problem posted. Nairobi. 12 minutes ago",
      "Brief opened. Nationwide. 2 hours ago",
    ]);
  });

  it("is left out when the feed cannot be read", async () => {
    const { container } = await home("2026-10-07T07:40:00Z", { activity: null });
    expect(container.querySelector("[data-home='activity']")).toBeNull();
  });
});

describe("Home's Your turn", () => {
  it("pulses on Needs you only, twice, and stands still under reduced motion", async () => {
    const { container } = await home("2026-10-07T07:40:00Z", { engagements: [summary({ id: "e1", whose_turn: ["developer"] })] });
    expect(container.querySelector("[data-home='needs-you'] [data-chip='turn']")).not.toBeNull();
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/\[data-home="needs-you"\] \[data-chip="turn"\] \{\s*animation: turn-pulse 2s var\(--ease-out\) 600ms 2 backwards;/);
    const reduced = css.slice(css.lastIndexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toContain('[data-home="needs-you"] [data-chip="turn"],');
  });
});
