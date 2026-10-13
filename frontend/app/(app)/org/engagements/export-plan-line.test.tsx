import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithPageStrings } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-ENG-17 (P28 re-check MINOR): on the Engagements list with engagements and no csv_export, the plan is said once:
// the tools row's plan line normally, and under ?export=plan only the export's own notice (the page's planLine wiring).

const ORG_ID = "0199c000-0000-7000-8000-0000000000a1";

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/org/engagements",
  useSearchParams: () => new URLSearchParams(),
  redirect: () => {
    throw new Error("redirect");
  },
  unstable_rethrow: () => undefined,
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/offline/OfflineSlot", () => ({ OfflineSlot: () => null }));
// One engagement, drawn as a stand-in card: the list has something, so its tools row (filter, CSV) is drawn.
vi.mock("@/components/engagements/EngagementCard", () => ({ EngagementCard: () => <article data-card="" /> }));
vi.mock("@/components/ui/ClockTicker", () => ({ ClockTicker: () => null }));
vi.mock("../data", () => ({
  orgContext: async () => ({
    me: { user: { id: "u" } },
    memberships: [{ org_id: ORG_ID, org_name: "Telco A (fixture)", roles: ["owner"] }],
    org: { org_id: ORG_ID, org_name: "Telco A (fixture)", roles: ["owner"] },
    missing: null,
    query: "",
  }),
  getTeaser: async () => null,
}));
vi.mock("@/components/tracker/data", () => ({
  orgEngagements: async () => ({
    ok: true,
    value: [{ id: "e1", proposal_id: "p1", state: "UNDER_REVIEW", whose_turn: ["org"], team: null }],
  }),
}));
const api = vi.hoisted(() => ({
  get: vi.fn(async (path: string) =>
    path === "/api/plans"
      ? {
          data: { plans: [{ code: "org_growth", name: "Growth", purchasable: true, limits: { csv_export: true } }] },
          response: new Response(null, { status: 200 }),
        }
      : {
          data: { plan: "org_claimed", side: "org", limits: { csv_export: false } },
          response: new Response(null, { status: 200 }),
        },
  ),
}));
vi.mock("@/lib/api/server", () => ({
  appNow: () => "2026-10-13T08:00:00Z",
  serverApi: () => ({ GET: api.get }),
  forwardHeaders: async () => ({}),
}));

const { default: EngagementsPage } = await import("./page");

afterEach(cleanup);

async function renderList(search: Record<string, string>) {
  const node = await EngagementsPage({ searchParams: Promise.resolve(search) } as never);
  return renderWithPageStrings(<>{await resolveServerTree(node)}</>);
}

describe("the plan, said once", () => {
  it("is the tools row's line on the list", async () => {
    await renderList({});
    expect(document.querySelectorAll("[data-card]")).toHaveLength(1);
    expect(document.querySelector("[data-csv-off]")?.textContent).toBe("CSV export comes with the Growth plan. See plans");
    expect(document.querySelector("[data-export-refusal]")).toBeNull();
  });

  it("is only the export's notice under ?export=plan", async () => {
    await renderList({ export: "plan" });
    expect(document.querySelectorAll("[data-card]")).toHaveLength(1);
    expect(document.querySelector('[data-export-refusal="plan"]')).not.toBeNull();
    expect(document.querySelector("[data-csv-off]")).toBeNull();
  });
});
