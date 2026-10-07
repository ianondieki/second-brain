import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Me } from "@/lib/auth/routing";

import { EngagementScreen } from "./EngagementScreen";
import type { Detail } from "./model";
import type { Tier2Share } from "./share";
import { Tier2Section } from "./Tier2Section";

// REQ-ENG-04 and docs/spec/06 6.1: the tracker's line under the title names the developer only once
// `developer_named` is true (a handle, said to be one, before); the full-proposal section shows the developer's share
// control or its date, and the organisation's way to open it only once shared, on organisation-origin engagements.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const share = vi.hoisted(() => ({ current: null as Tier2Share | null }));
vi.mock("./data", () => ({
  tier2ShareState: async () => share.current,
  engagementHistory: async () => ({ engagement_id: "e", chain_verified: true, events: [], endorsements: [] }),
  orgMembers: async () => [],
  engagementDocument: async () => null,
}));

const SHARED: Tier2Share = {
  engagement_id: "e",
  shared: true,
  grant_id: "g",
  source: "org_interest",
  shared_at: "2026-09-30T08:00:00Z",
  counts_as_unlock: true,
};
const NOT_SHARED: Tier2Share = { ...SHARED, shared: false, grant_id: null, source: null, shared_at: null };

const ME = { user: { id: "u-org" }, mfa: { enrolled: true } } as unknown as Me;

beforeEach(() => {
  share.current = NOT_SHARED;
});
afterEach(cleanup);

async function section(d: Detail) {
  return renderWithIntl(
    <>{await resolveServerTree(<Tier2Section detail={d} enrolled query="?org=o1" />)}</>,
  );
}

const orgInterest = (overrides: Partial<Detail> = {}) =>
  detail({ origin: "org_agent_match", state: "INTEREST_CONFIRMED", ...overrides });

describe("the full-proposal section", () => {
  it("shows the organisation nothing until the developer shares", async () => {
    const { container } = await section(orgInterest({ my_party: "org" }));
    expect(container.textContent).toBe("");
  });

  it("gives the organisation the way to open it once shared, keeping the chosen organisation", async () => {
    share.current = SHARED;
    const d = orgInterest({ my_party: "org" });
    await section(d);
    expect(screen.getByText(`The developer shared the full proposal with ${d.org_name} on 30 Sep 2026.`)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the full proposal" }).getAttribute("href")).toBe(
      `/org/inbox/${d.proposal_id}?org=o1`,
    );
  });

  it("tells the developer when they shared, with a stable place for focus", async () => {
    share.current = SHARED;
    const d = orgInterest({ my_party: "developer" });
    await section(d);
    const line = screen.getByText(`You shared the full proposal with ${d.org_name} on 30 Sep 2026.`);
    expect(line.id).toBe("share-status");
    expect(line.getAttribute("tabindex")).toBe("-1");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers the developer the share, as a secondary action", async () => {
    await section(orgInterest({ my_party: "developer" }));
    // The share loads with its own chunk (components/tracker/lazy.tsx).
    expect(await screen.findByRole("button", { name: "Share the full proposal" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("offers nothing on an ended engagement or a pitched one", async () => {
    const ended = await section(orgInterest({ my_party: "developer", state: "DECLINED" }));
    expect(ended.container.textContent).toBe("");
    cleanup();
    const pitched = await section(detail({ origin: "tagged", my_party: "developer" }));
    expect(pitched.container.textContent).toBe("");
  });
});

describe("the tracker's line under the title", () => {
  async function screenFor(d: Detail) {
    return renderWithIntl(
      <>{await resolveServerTree(await EngagementScreen({ detail: d, me: ME, tab: "tracker", doc: null, basePath: "/org/engagements" }))}</>,
    );
  }

  it("says the organisation sees a handle while the developer is not named", async () => {
    await screenFor(orgInterest({ my_party: "org", state: "ORG_INTEREST", developer_name: "dev-7k2m9qxp", developer_named: false }));
    const line = document.querySelector("[data-counterpart]")!;
    expect(line.getAttribute("data-counterpart")).toBe("fromHandle");
    expect(line.textContent).toBe(en.tracker.fromHandle.replace("{name}", "dev-7k2m9qxp"));
  });

  it("names the developer once they are named", async () => {
    await screenFor(orgInterest({ my_party: "org", developer_name: "Achieng Otieno", developer_named: true }));
    const line = document.querySelector("[data-counterpart]")!;
    expect(line.getAttribute("data-counterpart")).toBe("fromDeveloper");
    expect(line.textContent).toBe("From Achieng Otieno");
  });
});
