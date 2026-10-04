import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { brief, briefList, ORG_ID, ORG_NAME } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { BriefsRead } from "./brief-data";
import OrganisationHome from "./page";

// REQ-DIR-05 with D-52 (P19-F §F-B): the organisation Home keeps four stat tiles; the fourth counts the open Problem
// Briefs (in place of "Need us", whose engagements are the cards right below) and leads to Problems.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  redirect: () => {
    throw new Error("redirect");
  },
  unstable_rethrow: () => undefined,
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ nav, children }: { nav: ReactNode; children: ReactNode }) => (
    <>
      {nav}
      <main>{children}</main>
    </>
  ),
}));

const state = vi.hoisted(() => ({ briefs: null as BriefsRead | null }));
const membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] };
vi.mock("./data", () => ({
  orgContext: async () => ({
    me: { user: { display_name: "Rita Njeri" }, mfa: { enrolled: true, required: true, verified: true } },
    memberships: [membership],
    org: membership,
    missing: null,
    query: "",
  }),
  getInbox: async () => ({ kind: "page", page: { items: [], next_cursor: null, held_count: 0, verification: "e2" } }),
}));
vi.mock("./scout-data", () => ({ getMatches: async () => ({ kind: "ok", value: [] }) }));
vi.mock("@/components/tracker/data", () => ({ orgEngagements: async () => ({ ok: true, value: [] }) }));
vi.mock("./brief-data", () => ({
  getBriefs: async () => {
    if (!state.briefs) throw new Error("unreachable");
    return state.briefs;
  },
}));

beforeEach(() => {
  state.briefs = { kind: "ok", value: briefList() };
});
afterEach(cleanup);

async function home() {
  return renderWithIntl(<>{await resolveServerTree(await OrganisationHome({ searchParams: Promise.resolve({}) } as never))}</>);
}

function tile(name: string) {
  return document.querySelector<HTMLElement>(`[data-stat='${name}']`);
}

describe("the organisation Home's tiles", () => {
  it("are four, the last the open Problem Briefs, linking to Problems", async () => {
    await home();
    const tiles = within(screen.getByRole("region", { name: "At a glance" })).getAllByRole("listitem");
    expect(tiles).toHaveLength(4);
    expect(tile("needs-us")).toBeNull();
    const briefs = tile("briefs")!;
    expect(briefs.getAttribute("href")).toBe("/org/problems");
    expect(briefs.textContent).toBe("Problem Briefs1 open1 in review");
  });

  it("count the proposals answering published Briefs when none is in review", async () => {
    state.briefs = {
      kind: "ok",
      value: briefList({ items: [brief({ state: "published", proposal_count: 3 })], plan: { plan: "org_claimed", problem_briefs: 1, used: 1 } }),
    };
    await home();
    expect(tile("briefs")!.textContent).toBe("Problem Briefs1 open3 proposals");
  });

  it("say the Briefs could not be read rather than a confident zero", async () => {
    state.briefs = null; // the read throws
    await home();
    expect(tile("briefs")!.textContent).toBe(`Problem Briefs${en.orgHome.stats.unknown}${en.orgHome.stats.unavailable}`);
  });
});
