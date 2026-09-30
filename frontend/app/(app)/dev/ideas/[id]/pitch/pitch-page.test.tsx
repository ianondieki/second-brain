import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import PitchPage from "./page";

// The pitch page's reads (P16-D, REQ-UX-03): after the developer check, the idea list (title, status: the owner's
// check), the picker's page and the niche tree start together; the picker and the niches are used only once the idea
// is found and can be pitched, and their failure on any other path changes nothing (the same empty states as before).

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
  status: "published",
  fail: false,
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => {
    reads.order.push("me");
    return { side: "developer", user: { id: "u1" }, mfa: { enrolled: true }, memberships: [] };
  },
}));
vi.mock("../../data", () => ({
  myIdeas: async () => {
    reads.order.push("ideas");
    return [
      {
        id: ID,
        status: reads.status,
        moderation_state: "clear",
        title: "Fuel-level alerts for off-grid tower sites",
        niche: null,
        current_version_no: 1,
        cert_id: "PB84BJ14PGSAN5ZE",
        has_draft: false,
        published_at: "2026-09-30T05:00:00Z",
        updated_at: "2026-09-30T05:00:00Z",
      },
    ];
  },
}));
vi.mock("./data", () => ({
  pickerPage: async () => {
    reads.order.push("picker");
    await reads.gate;
    if (reads.fail) throw new Error("GET /api/me/proposals/{proposal_id}/pitch/orgs answered 500");
    return {
      kind: "page",
      picker: {
        groups: [],
        cap: { limit: 5, used: 0, remaining: 5, period_end: null },
        proposal_public: true,
        next_cursor: null,
      },
    };
  },
  nicheTree: async () => {
    reads.order.push("niches");
    await reads.gate;
    if (reads.fail) throw new Error("GET /api/directory/niches answered 500");
    return [];
  },
  chosenOptions: async () => [],
}));

const ID = "01a0f30a-cdee-70e7-bdac-2912717f8783";

async function open(id = ID) {
  const node = await PitchPage({ params: Promise.resolve({ id }), searchParams: Promise.resolve({}) } as never);
  return resolveServerTree(node);
}

beforeEach(() => {
  reads.order = [];
  reads.fail = false;
  reads.status = "published";
  reads.gate = new Promise<void>((resolve) => {
    reads.release = resolve;
  });
});
afterEach(() => {
  reads.release();
  cleanup();
});

describe("the pitch page's reads", () => {
  it("starts the idea list, the picker and the niche tree together after the developer check", async () => {
    const page = open();
    await vi.waitFor(() => expect(reads.order).toEqual(["me", "picker", "niches", "ideas"]));
    reads.release();
    renderWithIntl(<>{await page}</>);
    // Nothing to list yet: the picker's own empty state, so its answer was used.
    expect(screen.getByText(en.pitch.emptyAll)).toBeTruthy();
  });

  it("shows a held idea's reason even when the picker and the niches fail", async () => {
    reads.status = "draft";
    reads.fail = true;
    reads.release();
    renderWithIntl(<>{await open()}</>);
    expect(screen.getByText(en.pitch.blocked.draft)).toBeTruthy();
  });

  it("reads nothing after the developer check for an id that is not an idea's", async () => {
    reads.release();
    renderWithIntl(<>{await open("not-an-id")}</>);
    expect(reads.order).toEqual(["me"]);
    expect(screen.getByText(en.pitch.notFound)).toBeTruthy();
  });
});
