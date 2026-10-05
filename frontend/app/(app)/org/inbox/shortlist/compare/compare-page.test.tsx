import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { CompareRead } from "../../../shortlist-data";
import CompareScreen from "./page";

// REQ-REPO-02 (P21 B4): what the compare page shows for what the API returned. A proposal no longer available is
// left out and the page says how many were, also when only one is left to show (then nothing is compared).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ nav, children }: { nav: ReactNode; children: ReactNode }) => (
    <>
      {nav}
      <main>{children}</main>
    </>
  ),
}));
vi.mock("./CompareView", () => ({
  CompareView: ({ items }: { items: { proposal_id: string }[] }) => <div data-compare-view={items.length} />,
}));

const ORG = { org_id: "01a0f30a-c087-72be-ae4c-31dca2604454", org_name: "Telco A (fixture)", roles: ["viewer"] };
const state = vi.hoisted(() => ({ read: null as unknown }));
vi.mock("../../../data", () => ({
  orgContext: async () => ({ me: {}, memberships: [ORG], org: ORG, missing: null, query: "" }),
}));
vi.mock("../../../scout-data", () => ({ getCounties: async () => [] }));
vi.mock("../../../shortlist-data", () => ({ getCompare: async () => state.read }));

const IDS = ["01a0f30a-0000-7000-8000-000000000001", "01a0f30a-0000-7000-8000-000000000002"];

async function show(available: number) {
  state.read = {
    kind: "ok",
    value: { items: IDS.slice(0, available).map((proposal_id) => ({ proposal_id })) },
  } as unknown as CompareRead;
  const tree = await CompareScreen({
    searchParams: Promise.resolve({ ids: IDS.join(",") }),
  } as unknown as Parameters<typeof CompareScreen>[0]);
  renderWithIntl(<>{await resolveServerTree(tree)}</>);
}

afterEach(cleanup);

describe("compare page", () => {
  it("compares when both are available, with no left-out note", async () => {
    await show(2);
    expect(document.querySelector("[data-compare-view='2']")).not.toBeNull();
    expect(document.querySelector("[data-left-out]")).toBeNull();
  });

  it("with one left, says one was left out and that 2 to 4 are needed, and compares nothing", async () => {
    await show(1);
    expect(document.querySelector("[data-compare-view]")).toBeNull();
    expect(document.querySelector("[data-left-out='1']")).not.toBeNull();
    expect(screen.getByText("1 proposal you chose is no longer available, so it is left out.")).toBeTruthy();
    expect(screen.getByText("Choose 2 to 4 proposals from the shortlist to compare.")).toBeTruthy();
  });

  it("with none left, says none is available", async () => {
    await show(0);
    expect(document.querySelector("[data-compare-view]")).toBeNull();
    expect(screen.getByText("None of these proposals is available any more.")).toBeTruthy();
  });
});
