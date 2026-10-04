import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail } from "@/test/engagement";

import type { Me } from "@/lib/auth/routing";

import { EngagementScreen } from "./EngagementScreen";

// The tracker's reads (P16-D, REQ-UX-03): once the engagement is known, its history (the History tab, or an ended or
// paused engagement) and, for an approver, the organisation's members are read together, not one after the other.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const reads = vi.hoisted(() => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { order: [] as string[], gate, release: () => release() };
});
vi.mock("./data", () => ({
  engagementHistory: async () => {
    reads.order.push("history");
    await reads.gate;
    return { engagement_id: "e", chain_verified: true, events: [], endorsements: [] };
  },
  orgMembers: async () => {
    reads.order.push("members");
    await reads.gate;
    return [];
  },
  tier2ShareState: async () => null,
  engagementDocument: async () => null,
}));

const ME = { user: { id: "u-org" }, mfa: { enrolled: true } } as unknown as Me;

afterEach(() => reads.release());

describe("the tracker's reads", () => {
  it("reads the history and the approver's members together", async () => {
    const screen = EngagementScreen({
      detail: detail({ my_party: "org", actions: ["approve"] }),
      me: ME,
      tab: "history",
      doc: null,
      basePath: "/org/engagements",
    });
    await vi.waitFor(() => expect(reads.order).toEqual(["history", "members"]));
    reads.release();
    await screen;
  });

  it("reads no history for a paused engagement on the Tracker tab: paused_from names its stage (REQ-ENG-10)", async () => {
    reads.release();
    const before = reads.order.length;
    await EngagementScreen({
      detail: detail({ state: "ON_HOLD", stage_group: null, paused_from: "NEGOTIATION", whose_turn: [], awaiting: [] }),
      me: ME,
      tab: "tracker",
      doc: null,
      basePath: "/dev/engagements",
    });
    expect(reads.order.slice(before)).toEqual([]);
    await EngagementScreen({
      detail: detail({ state: "EXPIRED", stage_group: null, end_reason: "NO_REVIEW", whose_turn: [], awaiting: [], due: null }),
      me: ME,
      tab: "tracker",
      doc: null,
      basePath: "/dev/engagements",
    });
    expect(reads.order.slice(before)).toEqual(["history"]);
  });
});
