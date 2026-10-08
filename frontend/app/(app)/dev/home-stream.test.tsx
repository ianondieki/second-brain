import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import type { PublicActivity } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EmptyState } from "@/components/ui/EmptyState";
import { summary } from "@/test/engagement";

import { GreetingBand } from "./GreetingBand";
import { HomeContent } from "./HomeContent";

// P25 (REQ-UX-05, acceptance 2: LCP ≤ 2.5 s on /dev): Home's server render waits only for what the first screen shows
// (the greeting and the stat tiles: the engagements and the ideas). Every read starts at once; the six below what needs
// the developer stream in through one Suspense boundary, the last thing in the page's column, so the shell, the greeting
// photograph, the tiles, the two-step notice, the new-user empty state and "Needs you" flush first.

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
// The tiles' two reads answer; every read below never does. Each records when it started.
vi.mock("@/components/tracker/data", () => ({
  myEngagements: async () => {
    reads.started.push("engagements");
    return [];
  },
}));
vi.mock("./ideas/data", () => ({
  myIdeas: async () => {
    reads.started.push("ideas");
    return [];
  },
}));
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

/** The elements of a tree outside any Suspense boundary (server components unresolved: what the shell renders). */
function shell(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) node.forEach((child) => shell(child, found));
  else if (isValidElement(node)) {
    found.push(node);
    if (node.type !== Suspense) shell((node.props as { children?: ReactNode }).children, found);
  }
  return found;
}

const BELOW = ["activity", "mine", "peers", "quiz", "recommendations", "week"];

describe("Developer Home's first flush", () => {
  it("starts every read at once and waits only for the tiles' two", async () => {
    const { default: DeveloperHome } = await import("./page");
    const tree = await DeveloperHome(); // resolves although every read below is still under way
    expect([...reads.started].sort()).toEqual([...BELOW, "engagements", "ideas"].sort());
    // The six are under way before the tiles' reads are awaited: no step waits on another.
    const first = Math.min(reads.started.indexOf("engagements"), reads.started.indexOf("ideas"));
    for (const name of BELOW) expect(reads.started.indexOf(name)).toBeLessThan(first);

    const content = await (tree.type as typeof HomeContent)(tree.props);
    const outside = shell(content);
    const boundaries = outside.filter((element) => element.type === Suspense) as ReactElement<{ fallback: ReactNode }>[];
    expect(boundaries).toHaveLength(1);
    // Skeleton-free: nothing is drawn while the reads are under way, and nothing follows the boundary to move.
    expect(boundaries[0].props.fallback).toBeNull();
    const column = outside.find((element) => (element.props as { className?: string }).className?.includes("flex-col gap-12"))!;
    const kids = [(column.props as { children: ReactNode }).children].flat(3).filter(isValidElement);
    expect(kids[kids.length - 1]).toBe(boundaries[0]);
    // The greeting, the tiles and the new-user empty state (no engagements) are in the shell.
    expect(outside.some((element) => element.type === GreetingBand)).toBe(true);
    expect(outside.some((element) => (element.props as Record<string, unknown>)["data-home"] === "stats")).toBe(true);
    expect(outside.some((element) => element.type === EmptyState)).toBe(true);
  });

  it("keeps the two-step notice and Needs you in the shell", async () => {
    const waiting = summary({ id: "0199b000-0000-7000-8000-00000000e00a", state: "NDA_PENDING", whose_turn: ["developer"] });
    const noMfa = { ...ME, mfa: { enrolled: false, required: false, verified: true } } as unknown as Me;
    const content = await HomeContent({ me: noMfa, engagements: [waiting], ideas: [], recommended: never(), quiz: never(), activity: never() });
    const outside = shell(content);
    const homes = outside.map((element) => (element.props as Record<string, unknown>)["data-home"]).filter(Boolean);
    expect(homes).toEqual(["stats", "security", "needs-you"]);
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
    expect(order).toEqual(["stats", "activity", "recommended"]); // no engagements: the empty state, no Needs you
    expect(container.querySelector("[data-home='activity']")!.textContent).toContain("Late diesel deliveries");
  });
});
