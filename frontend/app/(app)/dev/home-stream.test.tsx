import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import type { PublicActivity } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { HomeContent } from "./HomeContent";

// P25 (REQ-UX-05, acceptance 2: LCP ≤ 2.5 s on /dev): Home's server render waits only for what the first screen shows
// (the greeting and the stat tiles: the engagements and the ideas). The reads below the tiles start after those and
// stream in through one Suspense boundary that nothing follows, so the shell and the greeting photograph flush first.

const never = <T,>() => new Promise<T>(() => undefined);
const ME = { side: "developer", user: { display_name: "Amina" }, mfa: { enrolled: true, required: false, verified: true } } as unknown as Me;
const ACTIVITY: PublicActivity = {
  generated_at: "2026-10-07T07:40:00Z",
  seeded: true,
  items: [{ id: "a", kind: "problem_posted", at: "2026-10-07T07:28:00Z", county: "Nairobi", niche: "ICT", title: "Late diesel deliveries", stage: null, seeded: true }],
};

const reads = vi.hoisted(() => ({ started: [] as string[] }));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }), headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn(), useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("@/lib/api/server", () => ({ requireMe: async () => ME, appNow: () => "2026-10-07T07:40:00Z" }));
// The tiles' two reads answer; every read below the tiles never does, and records that it started.
vi.mock("@/components/tracker/data", () => ({ myEngagements: async () => [] }));
vi.mock("./ideas/data", () => ({ myIdeas: async () => [] }));
const pending = (name: string) => () => {
  reads.started.push(name);
  return never();
};
vi.mock("./discover/data", () => ({ recommendations: pending("recommendations") }));
vi.mock("./quiz/data", () => ({ quizCard: pending("quiz") }));
vi.mock("./week/data", () => ({ weekStrip: pending("week") }));
vi.mock("./teams/data", () => ({ homePeers: pending("peers") }));
vi.mock("@/lib/public/public-data", () => ({ publicActivity: pending("activity") }));
vi.mock("@/components/activity/fetch", () => ({ getActivity: pending("mine") }));

afterEach(cleanup);

/** The Suspense boundaries an element tree holds (server components unresolved: what the shell renders). */
function boundaries(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) node.forEach((child) => boundaries(child, found));
  else if (isValidElement(node)) {
    if (node.type === Suspense) found.push(node);
    const props = node.props as { children?: ReactNode };
    boundaries(props.children, found);
  }
  return found;
}

describe("Developer Home's first flush", () => {
  it("renders the greeting and the tiles without waiting for the reads below them, which have started", async () => {
    const { default: DeveloperHome } = await import("./page");
    const tree = await DeveloperHome(); // resolves although every read below the tiles is still under way
    expect(reads.started.sort()).toEqual(["activity", "mine", "peers", "quiz", "recommendations", "week"]);
    const content = await (tree.type as typeof HomeContent)(tree.props);
    const [below] = boundaries(content);
    expect(below).toBeDefined();
    // Skeleton-free: nothing is drawn while the reads are under way, and nothing follows the boundary to move.
    expect((below.props as { fallback: ReactNode }).fallback).toBeNull();
  });

  it("draws the reads below the tiles once they answer, in Home's order", async () => {
    const { container } = renderWithIntl(
      <>
        {await resolveServerTree(
          await HomeContent({
            me: ME,
            engagements: [],
            ideas: [],
            recommended: Promise.resolve({ kind: "unavailable" }),
            activity: Promise.resolve(ACTIVITY),
            quiz: Promise.resolve(null),
            week: Promise.resolve(null),
            peers: Promise.resolve(null),
            mine: Promise.resolve(null),
            now: "2026-10-07T07:40:00Z",
          }),
        )}
      </>,
    );
    const order = [...container.querySelectorAll<HTMLElement>("[data-home]")].map((el) => el.dataset.home);
    expect(order).toEqual(["stats", "activity", "recommended"]);
    expect(container.querySelector("[data-home='activity']")!.textContent).toContain("Late diesel deliveries");
  });
});
