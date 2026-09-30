import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Plan } from "../plans";
import UpgradePage from "./page";

// The checkout page's reads (P16-D, REQ-UX-03): the plan catalogue and the subject's live plan are read together
// (unless a checkout is resuming), and the plan asked for is still checked first: an unknown plan says so even when
// the live plan cannot be read.

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

const PRO: Plan = {
  code: "dev_pro_monthly",
  side: "developer",
  name: "Pro (monthly)",
  price_kes_minor: 49900,
  interval: "month",
  limits: {},
  is_default: false,
  purchasable: true,
  upgrade_to: null,
};
const reads = vi.hoisted(() => ({
  order: [] as string[],
  release: () => {},
  gate: Promise.resolve(),
  currentFails: false,
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => {
    reads.order.push("me");
    return { side: "developer", user: { id: "u1" }, mfa: { enrolled: true }, memberships: [] };
  },
}));
vi.mock("../data", () => ({
  getPlans: async () => {
    reads.order.push("plans");
    await reads.gate;
    return { plans: [PRO], simulated_checkout: true, sample_prices: false };
  },
  getCurrentPlan: async () => {
    reads.order.push("current");
    await reads.gate;
    if (reads.currentFails) throw new Error("GET entitlements answered 500");
    return { kind: "plan", code: "dev_free" };
  },
  planName: async () => null,
}));

async function open(search: Record<string, string>) {
  const node = await UpgradePage({ searchParams: Promise.resolve(search) } as never);
  return resolveServerTree(node);
}

beforeEach(() => {
  reads.order = [];
  reads.currentFails = false;
  reads.gate = new Promise<void>((resolve) => {
    reads.release = resolve;
  });
});
afterEach(() => {
  reads.release();
  cleanup();
});

describe("the checkout page's reads", () => {
  it("reads the catalogue and the live plan together", async () => {
    const page = open({ plan: "dev_pro_monthly" });
    await vi.waitFor(() => expect(reads.order).toEqual(["me", "current", "plans"]));
    reads.release();
    renderWithIntl(<>{await page}</>);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Pro (monthly)");
  });

  it("says a plan is unknown even when the live plan cannot be read", async () => {
    reads.currentFails = true;
    reads.release();
    renderWithIntl(<>{await open({ plan: "dev_gold" })}</>);
    expect(screen.getByText(en.billing.refused.unknownPlan)).toBeTruthy();
  });

  it("reads no live plan while a checkout resumes, and nothing for a code that is not a plan's", async () => {
    reads.release();
    await open({ plan: "dev_pro_monthly", checkout: "0192a7c4-5b1e-7c3d-8e9f-00000000000a" });
    expect(reads.order).toEqual(["me", "plans"]);
    reads.order = [];
    renderWithIntl(<>{await open({ plan: "../x" })}</>);
    expect(reads.order).toEqual(["me"]);
    expect(screen.getByText(en.billing.refused.unknownPlan)).toBeTruthy();
  });
});
