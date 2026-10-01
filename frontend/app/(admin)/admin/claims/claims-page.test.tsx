import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import ClaimPage from "./[id]/page";
import type { Claim, ClaimDetail } from "./claims";
import ClaimsPage from "./page";

// REQ-DIR-03 queue (read only; docs/spec/06 6.2 "admin claim queue with the 2 BD SLA shown"): the review time left as
// a mark and words, organisations staff cannot read named by id, personal and registration details on the claim's own
// page only, and no decision anywhere.

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
  notFound: () => {
    throw new Error("notFound");
  },
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("../AdminShell", () => ({ AdminShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));

const staff = vi.hoisted(() => ({ role: "admin" as "admin" | "moderator" }));
vi.mock("../staff", () => ({ staffContext: async () => ({ me: {}, role: staff.role }) }));

const data = vi.hoisted(() => ({
  items: [] as Claim[],
  detail: null as ClaimDetail | null,
  stepUp: false,
}));
vi.mock("./data", () => ({
  getClaims: async () =>
    data.stepUp ? { kind: "stepUp" } : { kind: "ok", data: { items: data.items, reviewSlaDays: 2 } },
  getClaim: async () => (data.stepUp ? { kind: "stepUp" } : { kind: "ok", data: data.detail }),
}));

const CLAIM_ID = "01a0f016-2e64-7294-9e44-77fa421dce09";
const ORG_ID = "01a0e001-aaaa-7bbb-8ccc-000000000001";

function claim(extra: Partial<Claim> = {}): Claim {
  return {
    id: CLAIM_ID,
    org: {
      id: ORG_ID,
      legal_name: "County Government of C (fixture)",
      slug: "county-c",
      kind: "county_govt",
      verification: "e1",
    },
    claimant: { id: "01a0e002-0000-7000-8000-000000000002", display_name: "Hassan Abdi" },
    domain: "county-c.example",
    level: "e2",
    status: "pending_review",
    created_at: "2026-09-30T05:00:00Z",
    updated_at: "2026-09-30T05:00:00Z",
    decided_at: null,
    otp_verified: true,
    dns_verified: false,
    sla: { due_on: "2026-10-02", business_days_left: 2, overdue: false },
    dispute_case_id: null,
    ...extra,
  };
}

function detail(extra: Partial<ClaimDetail> = {}): ClaimDetail {
  return {
    ...claim(),
    email_address: "owner@county-c.example",
    otp_verified_at: "2026-09-30T05:05:00Z",
    dns_verified_at: null,
    otp_attempts: 1,
    otp_reissues: 0,
    registration_no: "CPR/2013/0042",
    cr12_date: "2026-09-01",
    kra_pin: "P051234567Z",
    sector_register: null,
    public_entity_requested: true,
    document_count: 0,
    official_domains: ["county-c.example"],
    verified_domain: "county-c.example",
    domain_is_official: true,
    reviewed_by: null,
    decision_reason: null,
    other_claims: [],
    cases: [],
    ...extra,
  };
}

async function list(view?: string) {
  const searchParams = Promise.resolve(view ? { view } : {});
  return renderWithIntl(<>{await resolveServerTree(await ClaimsPage({ searchParams } as never))}</>);
}

async function page(id = CLAIM_ID) {
  return renderWithIntl(<>{await resolveServerTree(await ClaimPage({ params: Promise.resolve({ id }) } as never))}</>);
}

beforeEach(() => {
  staff.role = "admin";
  data.items = [];
  data.detail = detail();
  data.stepUp = false;
});
afterEach(cleanup);

describe("the claims queue", () => {
  it("shows the review time left as a mark and words, and no personal or registration details", async () => {
    data.items = [
      claim(),
      claim({
        id: "01a0f017-0000-7000-8000-000000000017",
        sla: { due_on: "2026-09-28", business_days_left: -1, overdue: true },
      }),
      claim({
        id: "01a0f018-0000-7000-8000-000000000018",
        sla: { due_on: "2026-09-30", business_days_left: 0, overdue: false },
      }),
    ];
    const { container } = await list();
    expect(screen.getByText("Staff review a claim within 2 business days.", { exact: false })).toBeTruthy();
    const rows = [...container.querySelectorAll<HTMLElement>("[data-claim]")];
    expect(rows.map((row) => row.querySelector("[data-sla]")!.textContent)).toEqual([
      "Due in 2 business days",
      "Overdue",
      "Due today",
    ]);
    for (const row of rows) {
      expect(row.querySelector("[data-sla] svg"), "a mark beside the words").not.toBeNull();
      expect(row.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    }
    expect(rows[1].querySelector('[data-mark="overdue"]')).not.toBeNull();
    expect(container.textContent).not.toContain("P051234567Z");
    expect(container.textContent).not.toContain("CPR/2013/0042");
    expect(container.textContent).not.toContain("owner@county-c.example");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0); // nothing to decide
    expect(container.querySelector("button")).toBeNull();
    expect(screen.getByRole("table", { name: "Claims waiting for review, oldest first" })).toBeTruthy();
    expect(within(rows[0]).getByRole("link").getAttribute("href")).toBe(`/admin/claims/${CLAIM_ID}`);
    // D-52: a dense table; each row's title is its row header, so no heading sits inside the table.
    for (const row of rows) expect(row.querySelector("th a[data-claim-link]")).not.toBeNull();
    expect(container.querySelector("h3")).toBeNull();
  });

  it("names an organisation staff cannot read by its id, with a plain note", async () => {
    data.items = [claim({ org: { id: ORG_ID, legal_name: null, slug: null, kind: null, verification: null } })];
    const { container } = await list();
    const row = container.querySelector<HTMLElement>("[data-claim]")!;
    expect(within(row).getByRole("link").textContent).toBe("Organisation 01a0e001");
    expect(row.textContent).toContain(
      "Staff cannot see this organisation's name because it is not listed in the directory.",
    );
  });

  it("shows a dispute and the other views' statuses as a tag", async () => {
    data.items = [claim({ status: "disputed", sla: null, dispute_case_id: "01a0f019-0000-7000-8000-000000000019" })];
    await list();
    expect(screen.getByText("Disputed: a competing claim")).toBeTruthy();
    cleanup();
    data.items = [claim({ status: "approved", sla: null, decided_at: "2026-09-30T08:00:00Z" })];
    await list("closed");
    expect(screen.getByText("Approved")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Closed" }).getAttribute("aria-current")).toBe("page");
  });

  it.each([
    [undefined, "No claims are waiting for review.", "See claims in progress"],
    ["in_progress", "No claims are waiting for the claimant.", "See claims waiting for review"],
    ["closed", "No claim has been closed yet.", "See claims waiting for review"],
  ])("shows an empty view (%s) as one sentence and one action", async (view, sentence, action) => {
    const { container } = await list(view);
    const empty = container.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe(sentence);
    expect(
      within(empty)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual([action]);
  });

  it("tells a moderator claims are for staff admins", async () => {
    staff.role = "moderator";
    await list();
    expect(screen.getByText("Claims are for staff admins.")).toBeTruthy();
  });

  it("asks for a fresh code when the second factor is stale", async () => {
    data.stepUp = true;
    await list();
    expect(screen.getByLabelText("Code from your app")).toBeTruthy();
  });
});

describe("a claim", () => {
  it("shows the evidence, the SLA and one sentence that decisions are not in the prototype, with no decision buttons", async () => {
    const { container } = await page();
    expect(screen.getByRole("heading", { level: 1, name: "County Government of C (fixture)" })).toBeTruthy();
    expect(container.querySelector("[data-read-only]")!.textContent).toBe(
      "Deciding claims is not part of this prototype, so this page is for reading only.",
    );
    expect(container.querySelector('[data-pii="kra_pin"]')!.textContent).toBe("P051234567Z");
    expect(container.querySelector('[data-pii="registration_no"]')!.textContent).toBe("CPR/2013/0042");
    expect(screen.getByText("owner@county-c.example")).toBeTruthy();
    expect(container.querySelector("[data-sla]")!.textContent).toBe("Due in 2 business days");
    expect(screen.getByText("Due by the end of 2 Oct 2026.")).toBeTruthy();
    expect(screen.getByText("None uploaded")).toBeTruthy();
    expect(screen.getByText("Documents cannot be opened in this prototype.")).toBeTruthy();
    expect(screen.getByText("County government")).toBeTruthy();
    expect(screen.getByText("Domain verified (E1)")).toBeTruthy();
    expect(container.querySelector("button")).toBeNull();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
    // One label column for every group of facts (DescriptionList), and headings in order.
    expect(container.querySelectorAll("dl").length).toBeGreaterThan(3);
    const levels = [...container.querySelectorAll("h1, h2, h3")].map((h) => Number(h.tagName[1]));
    for (let i = 1; i < levels.length; i++) expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
  });

  it("names an organisation staff cannot read by its whole id", async () => {
    data.detail = detail({ org: { id: ORG_ID, legal_name: null, slug: null, kind: null, verification: null } });
    await page();
    expect(screen.getByRole("heading", { level: 1, name: `Organisation ${ORG_ID}` })).toBeTruthy();
    expect(
      screen.getByText("Staff cannot see this organisation's name because it is not listed in the directory."),
    ).toBeTruthy();
  });

  it("reads an unknown or malformed id as no such claim", async () => {
    data.detail = null;
    await page();
    expect(screen.getByText("There is no such claim.")).toBeTruthy();
    cleanup();
    await page("../../etc");
    expect(screen.getByText("There is no such claim.")).toBeTruthy();
  });
});
