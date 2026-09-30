import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import type { MatchDetail } from "../../../scout";
import MatchScreen from "./page";

// The match page's reads (P16-D, REQ-UX-03): membership first (orgContext), then the match of that organisation, then
// its teaser and, only when Express interest is offered, the organisation's members, together rather than one after
// the other. The signed-in person comes from orgContext: the page does not ask for it again.

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
const reads = vi.hoisted(() => ({
  order: [] as string[],
  release: () => {},
  gate: Promise.resolve(),
  interest: { allowed: true, reason: null } as { allowed: boolean; reason: string | null },
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => {
    reads.order.push("requireMe");
    throw new Error("the page asked for the signed-in person again");
  },
}));
const ORG = { org_id: "01a0f30a-c087-72be-ae4c-31dca2604454", org_name: "Telco A (fixture)", roles: ["signatory"] };
const ME = { user: { id: "u1" }, mfa: { enrolled: true }, memberships: [ORG] };
vi.mock("../../../data", () => ({
  orgContext: async () => {
    reads.order.push("orgContext");
    return { me: ME, memberships: [ORG], org: ORG, missing: null, query: "" };
  },
  getTeaser: async () => {
    reads.order.push("teaser");
    await reads.gate;
    return null;
  },
}));
vi.mock("../../../scout-data", () => ({
  getMatch: async () => {
    reads.order.push("match");
    return { kind: "ok", value: match() };
  },
  getMembers: async () => {
    reads.order.push("members");
    await reads.gate;
    return [{ user_id: "u2", display_name: "Rita Njeri", roles: ["reviewer"] }];
  },
}));

const MATCH_ID = "01a0f30a-ecc2-73f2-ac59-2d80df13a7e8";

function match(): MatchDetail {
  return {
    id: MATCH_ID,
    scout_id: "s1",
    proposal_id: "01a0f30a-ec2d-7335-b592-4b2e86ff7fb8",
    available: true,
    owner_handle: "jacaranda-otter-17",
    teaser: {
      title: "Maziwa baridi",
      niche: null,
      country: "KE",
      county_code: null,
      maturity: "mvp",
      ask: "pilot",
      problem_statement: "Milk spoils overnight.",
      impact_claims: null,
      summary: "Shared solar chillers.",
    },
    niche: null,
    score: 82,
    why: "Fits the niche.",
    why_source: "code",
    demo_fallback: false,
    injection_suspected: false,
    created_at: "2026-09-30T05:00:00Z",
    digest_sent_at: null,
    feedback: null,
    feedback_reason: null,
    rule_breakdown: null,
    engagement_id: null,
    interest: reads.interest,
  } as unknown as MatchDetail;
}

async function open() {
  const tree = MatchScreen({
    params: Promise.resolve({ matchId: MATCH_ID }),
    searchParams: Promise.resolve({}),
  } as never);
  return tree.then((node) => resolveServerTree(node));
}

beforeEach(() => {
  reads.order = [];
  reads.gate = new Promise<void>((resolve) => {
    reads.release = resolve;
  });
});
afterEach(() => reads.release());

describe("the match page's reads", () => {
  it("reads the teaser and the members together once the match is known, and not the person again", async () => {
    reads.interest = { allowed: true, reason: null };
    const page = open();
    // Both started before either answered: a read that waited for the other would leave "members" out here.
    await vi.waitFor(() => expect(reads.order).toEqual(["orgContext", "match", "teaser", "members"]));
    reads.release();
    await page;
    expect(reads.order).not.toContain("requireMe");
  });

  it("does not read the members when Express interest is not offered", async () => {
    reads.interest = { allowed: false, reason: "role_required" };
    reads.release();
    await open();
    expect(reads.order).toEqual(["orgContext", "match", "teaser"]);
  });
});
