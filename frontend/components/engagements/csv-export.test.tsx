import { cleanup, render, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

// REQ-ENG-17 (P28 track D, AT-D-2 on the web): the organisation's Engagements list offers "Export CSV" as a plain
// same-origin download link when its plan has csv_export, else one muted line naming the plan on sale that has it,
// linking to Plan & billing; nothing when the plan cannot be read.

const ORG_ID = "0199c000-0000-7000-8000-0000000000a1";
const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: mocks.get }),
  forwardHeaders: async () => ({ cookie: "bridge_session=s" }),
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({ unstable_rethrow: () => undefined }));

const { CsvExport, csvPlan, ExportRefusalNotice } = await import("./CsvExport");

const PLANS = [
  { code: "org_claimed", name: "Claimed (Free)", purchasable: false, limits: { csv_export: false } },
  { code: "org_starter", name: "Starter", purchasable: true, limits: { csv_export: false } },
  { code: "org_growth", name: "Growth", purchasable: true, limits: { csv_export: true } },
  { code: "org_enterprise", name: "Enterprise / Government", purchasable: false, limits: { csv_export: true } },
];

function api({ limits, plans }: { limits?: Record<string, unknown> | Error; plans?: unknown[] | Error }) {
  mocks.get.mockImplementation(async (path: string) => {
    const answer = path === "/api/plans" ? plans : limits;
    if (answer instanceof Error) throw answer;
    if (answer === undefined) return { data: undefined, response: new Response(null, { status: 503 }) };
    const data = path === "/api/plans" ? { plans: answer } : { plan: "org_claimed", side: "org", limits: answer };
    return { data, response: new Response(null, { status: 200 }) };
  });
}

async function renderExport() {
  render(<>{await resolveServerTree(<CsvExport orgId={ORG_ID} />)}</>);
}

beforeEach(() => mocks.get.mockReset());
afterEach(cleanup);

describe("Export CSV", () => {
  it("is a plain link to the web app's export route when the plan has csv_export", async () => {
    api({ limits: { csv_export: true } });
    await renderExport();
    const link = screen.getByRole("link", { name: "Export CSV" });
    expect(link.getAttribute("href")).toBe(`/org/engagements/export?org=${ORG_ID}`);
    // No download attribute: a refusal comes back as the list page, which must open, not download.
    expect(link.hasAttribute("download")).toBe(false);
    expect(link.hasAttribute("data-primary")).toBe(false);
    const [path, options] = mocks.get.mock.calls[0];
    expect(path).toBe("/api/orgs/{org_id}/entitlements");
    expect(options.params).toEqual({ path: { org_id: ORG_ID } });
    expect(mocks.get).toHaveBeenCalledTimes(1); // the plans are not read when nothing needs naming
  });

  it("names the plan on sale that has it, linking to Plan & billing, when the plan does not", async () => {
    api({ limits: { csv_export: false }, plans: PLANS });
    await renderExport();
    expect(screen.queryByRole("link", { name: "Export CSV" })).toBeNull();
    const line = document.querySelector<HTMLElement>("[data-csv-off]")!;
    expect(line.textContent).toBe("CSV export comes with the Growth plan. See plans");
    expect(line.getAttribute("data-csv-off")).toBe("Growth");
    expect(screen.getByRole("link", { name: "See plans" }).getAttribute("href")).toBe(`/billing?org=${ORG_ID}`);
  });

  it("treats anything but an explicit true as off (a string such as 'release-2' grants nothing)", async () => {
    api({ limits: { csv_export: "release-2" }, plans: PLANS });
    await renderExport();
    expect(screen.queryByRole("link", { name: "Export CSV" })).toBeNull();
    expect(document.querySelector("[data-csv-off]")).not.toBeNull();
  });

  it("says it is not part of the plan when the plans cannot be read", async () => {
    api({ limits: {}, plans: new Error("timeout") });
    await renderExport();
    expect(document.querySelector("[data-csv-off]")?.textContent).toBe("CSV export is not part of your plan. See plans");
  });

  it("shows nothing when the plan itself cannot be read", async () => {
    api({ limits: undefined }); // the API answers 503
    await renderExport();
    expect(document.body.textContent).toBe("");
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("prefers a plan that can be bought", () => {
    expect(csvPlan(PLANS)).toBe("Growth");
    expect(csvPlan([PLANS[3]])).toBe("Enterprise / Government");
    expect(csvPlan(PLANS.slice(0, 2))).toBeNull();
  });
});

describe("why an export did not download", () => {
  async function notice(refusal: "plan" | "rateLimited" | "signedOut" | "notFound" | "failed", retry: number | null = null) {
    render(<>{await resolveServerTree(<ExportRefusalNotice refusal={refusal} retry={retry} orgId={ORG_ID} />)}</>);
    return document.querySelector<HTMLElement>(`[data-export-refusal="${refusal}"]`)!;
  }

  it("says the plan, with Plan & billing", async () => {
    const line = await notice("plan");
    expect(line.textContent).toBe("CSV export is not part of your plan. See plans");
    expect(screen.getByRole("link", { name: "See plans" }).getAttribute("href")).toBe(`/billing?org=${ORG_ID}`);
  });

  it("says roughly when to try again after too many exports", async () => {
    expect((await notice("rateLimited", 1800)).textContent).toBe("Too many exports just now. Try again in about 30 minutes.");
    cleanup();
    expect((await notice("rateLimited")).textContent).toBe("Too many exports just now. Try again later.");
  });

  it("asks to sign in again, and offers a retry when the file could not be made", async () => {
    await notice("signedOut");
    expect(screen.getByRole("link", { name: "Sign in again" }).getAttribute("href")).toBe("/login?next=%2Forg%2Fengagements");
    cleanup();
    await notice("failed");
    expect(screen.getByRole("link", { name: "Try again" }).getAttribute("href")).toBe(`/org/engagements/export?org=${ORG_ID}`);
    cleanup();
    expect((await notice("notFound")).textContent).toBe(en.engagements.exportNotFound);
  });
});
