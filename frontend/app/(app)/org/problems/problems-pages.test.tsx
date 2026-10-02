import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { brief, briefList, BRIEF_ID, ORG_ID, ORG_NAME } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { BriefsRead } from "../brief-data";
import type { Brief } from "../briefs";
import type { Membership } from "../membership";
import BriefPage from "./[id]/page";
import NewBriefPage from "./new/page";
import ProblemsPage from "./page";

// REQ-DIR-05 (docs/spec/07 items 1, 2, 4): the organisation's Problems list (state chip, proposals, deadline; at most
// two chips; one primary action; an empty state of one sentence and one action), the Brief's page (who sees it now,
// its facts, Close for the members who post) and the form's page (verification and role first, the plan's room).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
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

const state = vi.hoisted(() => ({
  membership: null as Membership | null,
  list: null as BriefsRead | null,
  one: null as { kind: "ok"; value: Brief } | null,
  verification: "e2" as string | null,
}));

vi.mock("../data", () => ({
  orgContext: async () => ({
    me: {},
    memberships: state.membership ? [state.membership] : [],
    org: state.membership,
    missing: state.membership ? null : "none",
    query: "",
  }),
}));
vi.mock("../brief-data", () => ({
  getBriefs: async () => state.list,
  getBrief: async () => state.one,
}));
vi.mock("../scout-data", () => ({
  getCounties: async () => [{ code: "KE-30", name: "Nairobi City" }],
  getNicheTree: async () => [{ id: "p", slug: "ict", name: "ICT", children: [] }],
  getVerification: async () => state.verification,
  getOrgPlans: async () => [
    { code: "org_claimed", name: "Claimed (Free)", purchasable: false, upgrade_to: "org_starter", limits: { problem_briefs: 1 } },
    { code: "org_starter", name: "Starter", purchasable: true, upgrade_to: null, limits: { problem_briefs: 5 } },
  ],
}));

const reviewer: Membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] };
const finance: Membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["finance"] };

beforeEach(() => {
  state.membership = reviewer;
  state.list = { kind: "ok", value: briefList() };
  state.one = { kind: "ok", value: brief() };
  state.verification = "e2";
});
afterEach(cleanup);

async function render(node: Promise<ReactNode>) {
  return renderWithIntl(<>{await resolveServerTree(await node)}</>);
}

const listPage = (search: Record<string, string> = {}) =>
  render(ProblemsPage({ searchParams: Promise.resolve(search) } as never));
const briefPage = () =>
  render(BriefPage({ params: Promise.resolve({ id: BRIEF_ID }), searchParams: Promise.resolve({}) } as never));
const newPage = () => render(NewBriefPage({ searchParams: Promise.resolve({}) } as never));

describe("the Problems list", () => {
  it("lists each Brief with its state, proposals and deadline, and Post a brief as the one primary action", async () => {
    state.list = {
      kind: "ok",
      value: briefList({
        items: [brief(), brief({ id: "01a0f070-0000-7000-8000-000000000002", title: "Closed one", state: "closed", proposal_count: 3, deadline: null })],
        plan: { plan: "org_starter", problem_briefs: 5, used: 1 },
      }),
    };
    await listPage();
    const nav = screen.getByRole("navigation", { name: "Organisation" });
    expect(within(nav).getByRole("link", { name: "Problems" }).getAttribute("aria-current")).toBe("page");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Post a Brief" }).getAttribute("href")).toBe("/org/problems/new");
    expect(document.querySelector("[data-plan-cap]")?.textContent).toBe("Open Briefs on your plan: 1 of 5");
    expect(document.querySelector("[data-plan-full]")).toBeNull();
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    // Heading order (axe): the page's h1, the list's (hidden) h2 naming the region, then each Brief's title as an h3.
    const list = screen.getByRole("region", { name: en.briefs.listLabel });
    expect(within(list).getByRole("heading", { level: 2 }).textContent).toBe(en.briefs.listLabel);
    expect(within(list).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Tower sites go dark when fuel runs out",
      "Closed one",
    ]);
    for (const card of cards) expect(card.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2); // AC-UX-1
    expect(cards[0].querySelector("[data-chip]")?.textContent).toBe("In review");
    expect(within(cards[0]).getByText("0 proposals")).toBeTruthy();
    expect(within(cards[0]).getByText("Proposals by 30 Nov 2026")).toBeTruthy();
    expect(within(cards[0]).getByText("Nairobi City")).toBeTruthy();
    expect(within(cards[0]).getByRole("link", { name: "Tower sites go dark when fuel runs out" }).getAttribute("href")).toBe(
      `/org/problems/${BRIEF_ID}`,
    );
    expect(cards[1].querySelector("[data-chip]")?.textContent).toBe("Closed");
    expect(within(cards[1]).getByText("3 proposals")).toBeTruthy();
    expect(within(cards[1]).getByText("No deadline")).toBeTruthy();
  });

  it("names the place Kenya when a Brief has no county, as the problem page does", async () => {
    state.list = { kind: "ok", value: briefList({ items: [brief({ county_code: null })] }) };
    await listPage();
    expect(within(screen.getByRole("article")).getByText("Kenya")).toBeTruthy();
  });

  it("says a new Brief went for review, in a live region that takes focus", async () => {
    await listPage({ posted: "1" });
    const status = screen.getByRole("status");
    expect(status.textContent).toBe(en.briefs.posted);
    expect(document.activeElement).toBe(status); // the form that had focus is gone
  });

  it("with every open Brief in use, says so once with the next plan, and Post a Brief is no longer primary", async () => {
    await listPage(); // the fixture's claimed plan: 1 of 1
    const full = document.querySelector<HTMLElement>("[data-plan-full]")!;
    expect(full.textContent).toContain(
      "Every open Brief your plan allows is in use (1 of 1). Close one, or move to Starter to post another.",
    );
    const links = within(full).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Upgrade to Starter", `/billing/upgrade?plan=org_starter&org=${ORG_ID}&next=%2Forg%2Fproblems`],
    ]);
    expect(document.querySelector("[data-plan-cap]")).toBeNull(); // one fact, said once
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Post a Brief" }).hasAttribute("data-primary")).toBe(false);
  });

  it("is one sentence and Post a brief when there is none yet", async () => {
    state.list = { kind: "ok", value: briefList({ items: [], plan: { plan: "org_claimed", problem_briefs: 1, used: 0 } }) };
    await listPage();
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(within(empty).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([
      `${ORG_NAME} has not posted a Brief yet: post one and developers can answer it with proposals.`,
    ]);
    const links = within(empty).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["Post a Brief", "/org/problems/new"]]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("offers a member who cannot post the Inbox instead, and no primary action", async () => {
    state.membership = finance;
    state.list = { kind: "ok", value: briefList({ items: [] }) };
    await listPage();
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(empty.textContent).toContain(`${ORG_NAME} has not posted a Brief yet.`);
    expect(within(empty).getByRole("link").textContent).toBe("Open the Inbox");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("does not offer Post a brief above a list to a member who cannot post", async () => {
    state.membership = finance;
    await listPage();
    expect(screen.queryByRole("link", { name: "Post a Brief" })).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });
});

describe("a Brief's page", () => {
  it.each([
    ["in_review", `Staff read every Brief before developers see it. Until then, only ${ORG_NAME} and staff can see it.`],
    ["published", en.briefs.stateNote.published],
    ["rejected", en.briefs.stateNote.rejected],
    ["closed", en.briefs.stateNote.closed],
  ] as const)("says who sees a Brief %s", async (briefState, note) => {
    state.one = { kind: "ok", value: brief({ state: briefState }) };
    await briefPage();
    expect(document.querySelector(`[data-state-note='${briefState}']`)?.textContent).toContain(note);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Tower sites go dark when fuel runs out");
  });

  it("shows the facts developers read and Close for a member who posts, with no primary action", async () => {
    state.one = { kind: "ok", value: brief({ state: "published", proposal_count: 2 }) };
    await briefPage();
    expect(screen.getByText("KES 100,000 – 1,000,000")).toBeTruthy();
    expect(screen.getByText("30 Nov 2026")).toBeTruthy();
    expect(screen.getByText("Rural subscribers")).toBeTruthy();
    expect(screen.getByText("2 proposals")).toBeTruthy();
    expect(screen.getByRole("link", { name: "See it as developers do" }).getAttribute("href")).toBe(`/problems/${BRIEF_ID}`);
    expect(screen.getByRole("button", { name: "Close this Brief" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("offers no Close while in review, once closed, or to a member who cannot post", async () => {
    for (const briefState of ["in_review", "closed", "rejected"] as const) {
      state.one = { kind: "ok", value: brief({ state: briefState }) };
      await briefPage();
      expect(screen.queryByRole("button", { name: "Close this Brief" }), briefState).toBeNull();
      cleanup();
    }
    state.one = { kind: "ok", value: brief({ state: "published" }) };
    state.membership = finance;
    await briefPage();
    expect(screen.queryByRole("button", { name: "Close this Brief" })).toBeNull();
  });

  it("says another organisation's or an unknown Brief is not available", async () => {
    state.one = null;
    await briefPage();
    expect(screen.getByText(en.briefs.notFound)).toBeTruthy();
  });
});

describe("the Post a brief page", () => {
  it("shows the form with what the plan allows while there is room", async () => {
    state.list = { kind: "ok", value: briefList({ plan: { plan: "org_starter", problem_briefs: 5, used: 1 } }) };
    await newPage();
    expect(document.querySelector("[data-brief-form]")).not.toBeNull();
    expect(document.querySelector("[data-plan-cap]")?.textContent).toBe("Open Briefs on your plan: 1 of 5");
    expect(document.querySelector("[data-plan-full]")).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("with every open Brief in use, shows the one notice with the next plan instead of the form", async () => {
    await newPage();
    expect(document.querySelector("[data-brief-form]")).toBeNull();
    expect(document.querySelector("[data-plan-cap]")).toBeNull();
    const notices = document.querySelectorAll<HTMLElement>("[data-plan-full]");
    expect(notices).toHaveLength(1);
    expect(within(notices[0]).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      `/billing/upgrade?plan=org_starter&org=${ORG_ID}&next=%2Forg%2Fproblems%2Fnew`,
    ]);
    expect(document.querySelectorAll("[data-upgrade]")).toHaveLength(1);
  });

  it("at the top of the ladder says to close one, with no upgrade link", async () => {
    state.list = { kind: "ok", value: briefList({ plan: { plan: "org_starter", problem_briefs: 5, used: 5 } }) };
    await newPage();
    const full = document.querySelector<HTMLElement>("[data-plan-full]")!;
    expect(full.textContent).toBe("Every open Brief your plan allows is in use (5 of 5). Close one to post another.");
    expect(within(full).queryAllByRole("link")).toHaveLength(0);
  });

  it("says an organisation that is not legally verified cannot post yet, instead of the form", async () => {
    state.verification = "e1";
    await newPage();
    expect(document.querySelector("[data-brief-form]")).toBeNull();
    expect(screen.getByText(`${ORG_NAME} can post Briefs once its legal verification is complete.`)).toBeTruthy();
  });

  it("says who can post to a member who cannot", async () => {
    state.membership = finance;
    await newPage();
    expect(document.querySelector("[data-brief-form]")).toBeNull();
    expect(screen.getByText(`Only an owner, admin, signatory or reviewer of ${ORG_NAME} can post a Brief.`)).toBeTruthy();
  });
});
