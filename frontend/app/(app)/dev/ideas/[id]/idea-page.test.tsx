import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { MyProposal, Version } from "../ideas";
import IdeaPage from "./page";

// The idea page's reads (P16-D, REQ-UX-03): the signed-in developer, then the idea (the owner's read, audited by the
// API), then together its pitches and views (a registered idea only) and the county's name for the teaser, instead
// of the county after the others. An idea that is not yours reads nothing more.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));

const reads = vi.hoisted(() => ({
  order: [] as string[],
  release: () => {},
  gate: Promise.resolve(),
  idea: null as unknown,
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => {
    reads.order.push("me");
    return { side: "developer", user: { id: "u1" }, mfa: { enrolled: true }, memberships: [] };
  },
}));
vi.mock("../data", () => ({
  myIdea: async () => {
    reads.order.push("idea");
    return reads.idea;
  },
  countyName: async (code: string) => {
    reads.order.push("county");
    await reads.gate;
    return code === "KE-30" ? "Nairobi City" : code;
  },
}));
vi.mock("./pitch/data", () => ({
  ideaTags: async () => {
    reads.order.push("tags");
    await reads.gate;
    return { items: [], cap: { limit: 5, used: 0, remaining: 5, period_end: null } };
  },
  ideaViews: async () => {
    reads.order.push("views");
    await reads.gate;
    return { items: [] };
  },
}));

const ID = "01a0f30a-cdee-70e7-bdac-2912717f8783";

function version(county: string | null): Version {
  return {
    id: "v1",
    version_no: 1,
    status: "published",
    cert_id: "PB84BJ14PGSAN5ZE",
    registered_at: "2026-09-30T05:00:00Z",
    provenance: null,
    teaser: {
      title: "Fuel-level alerts for off-grid tower sites",
      niche: null,
      country: "KE",
      county_code: county,
      maturity: "mvp",
      ask: "pilot",
      problem_statement: "Generators run dry.",
      impact_claims: null,
      summary: "Alerts before the tank is empty.",
    },
    problems: [],
    new_problem: null,
    confidential: { approach: null, architecture: null, pricing: null, notes: null, links: [], attachments: [] },
  } as unknown as Version;
}

function idea(registered: boolean, county: string | null): MyProposal {
  return {
    id: ID,
    status: registered ? "published" : "draft",
    moderation: { state: "clear", message: null },
    published_at: registered ? "2026-09-30T05:00:00Z" : null,
    hidden_at: null,
    current: registered ? version(county) : null,
    draft: registered ? null : version(county),
  } as unknown as MyProposal;
}

async function open() {
  const node = await IdeaPage({ params: Promise.resolve({ id: ID }), searchParams: Promise.resolve({}) } as never);
  return resolveServerTree(node);
}

beforeEach(() => {
  reads.order = [];
  reads.gate = new Promise<void>((resolve) => {
    reads.release = resolve;
  });
});
afterEach(() => {
  reads.release();
  cleanup();
});

describe("the idea page's reads", () => {
  it("reads the pitches, the views and the county together once the idea is known to be yours", async () => {
    reads.idea = idea(true, "KE-30");
    const page = open();
    // All three started before any answered: a read that waited for another would be missing here.
    await vi.waitFor(() => expect(reads.order).toEqual(["me", "idea", "tags", "views", "county"]));
    reads.release();
    renderWithIntl(<>{await page}</>);
    expect(screen.getByText("Nairobi City")).toBeTruthy();
  });

  it("reads only the county for a draft never registered, and nothing more for an idea that is not yours", async () => {
    reads.release();
    reads.idea = idea(false, "KE-30");
    await open();
    expect(reads.order).toEqual(["me", "idea", "county"]);

    reads.order = [];
    reads.idea = null;
    await open();
    expect(reads.order).toEqual(["me", "idea"]);
  });

  it("reads no county when the teaser names none", async () => {
    reads.release();
    reads.idea = idea(true, null);
    await open();
    expect(reads.order).toEqual(["me", "idea", "tags", "views"]);
  });
});
