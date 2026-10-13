import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithPageStrings } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-ENG-17 (P28 re-check MINOR 4): the Engagements list says why the last export did not download from the export
// route's ?export= and ?retry= (seconds); a ?retry= that is not a number says "Try again later." without a figure.

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
vi.mock("@/components/tracker/data", () => ({ orgEngagements: async () => ({ ok: true, value: [] }) }));
vi.mock("@/lib/api/server", () => ({ appNow: () => "2026-10-13T08:00:00Z", serverApi: () => ({ GET: vi.fn() }) }));

const { default: EngagementsPage } = await import("./page");

afterEach(cleanup);

async function renderList(search: Record<string, string>) {
  const node = await EngagementsPage({ searchParams: Promise.resolve(search) } as never);
  return renderWithPageStrings(<>{await resolveServerTree(node)}</>);
}

describe("why the export did not download", () => {
  it("says roughly when to try again from ?retry=", async () => {
    await renderList({ export: "rateLimited", retry: "900" });
    expect(document.querySelector('[data-export-refusal="rateLimited"]')?.textContent).toBe(
      "Too many exports just now. Try again in about 15 minutes.",
    );
  });

  it("says Try again later for a ?retry= that is not a number", async () => {
    await renderList({ export: "rateLimited", retry: "abc" });
    expect(document.querySelector('[data-export-refusal="rateLimited"]')?.textContent).toBe(
      "Too many exports just now. Try again later.",
    );
  });

  it("says nothing for an ?export= it does not know", async () => {
    await renderList({ export: "<script>" });
    expect(document.querySelector("[data-export-refusal]")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(en.tracker.title);
  });
});
