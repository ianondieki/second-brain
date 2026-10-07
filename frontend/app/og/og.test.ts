// @vitest-environment node
import { createTranslator } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

// P24 (REQ-UX-04): the share cards, from public reads only (a link preview's crawler has no session). A public problem
// and a found certificate answer a 1200 × 630 PNG; a problem that is not public, an unknown certificate and a malformed
// id answer 404 with no image.

const problem = vi.hoisted(() => vi.fn());
const lookup = vi.hoisted(() => vi.fn());
vi.mock("@/lib/public/public-data", () => ({ publicProblem: problem }));
vi.mock("@/app/(public)/verify/lookup", () => ({ lookupCertificate: lookup }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

const { GET: problemCard } = await import("./problem/[id]/route");
const { GET: verifyCard } = await import("./verify/[id]/route");

const SEEDED = "0199b000-0000-7000-8000-0000000000aa";
const ctx = (id: string) => ({ params: Promise.resolve({ id }) }) as never;
const PROBLEM = {
  id: SEEDED,
  title: "Late diesel deliveries darken tower sites",
  statement: "…",
  affected_group: null,
  source: "brief",
  posted_at: "2026-10-07T07:00:00Z",
  county: { code: "KE-30", name: "Nairobi" },
  niche: { id: "n", name: "Networks & Telecommunications", parent: { id: "p", name: "ICT" } },
  organisation: { verification: "e2" },
  seeded: true,
};

async function isPng(response: Response) {
  const bytes = new Uint8Array(await response.arrayBuffer());
  return [...bytes.slice(0, 4)].join(",") === "137,80,78,71";
}

beforeEach(() => {
  problem.mockReset();
  lookup.mockReset();
});

describe("GET /og/problem/<id>", () => {
  it("draws a public problem's title and niche as a PNG", async () => {
    problem.mockResolvedValue({ kind: "found", problem: PROBLEM });
    const response = await problemCard(new Request("http://x/og/problem"), ctx(SEEDED));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(await isPng(response)).toBe(true);
    expect(problem).toHaveBeenCalledWith(SEEDED);
  }, 30_000);

  it("answers 404 with no image for a problem that is not public, or when the API cannot say", async () => {
    for (const kind of ["notFound", "unavailable"]) {
      problem.mockResolvedValue({ kind });
      const response = await problemCard(new Request("http://x/og/problem"), ctx(SEEDED));
      expect(response.status).toBe(404);
      expect(response.headers.get("content-type")).toBeNull();
    }
  });
});

describe("GET /og/verify/<certificate id>", () => {
  it("draws a found certificate's id and 'Registered on Wazo'", async () => {
    lookup.mockResolvedValue({ kind: "found", record: {} });
    const response = await verifyCard(new Request("http://x/og/verify"), ctx("wyp2c35185cqf7k3"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(await isPng(response)).toBe(true);
    expect(lookup).toHaveBeenCalledWith("WYP2C35185CQF7K3");
  }, 30_000);

  it("answers 404 for an unknown certificate and for an id that cannot be one", async () => {
    lookup.mockResolvedValue({ kind: "notFound" });
    expect((await verifyCard(new Request("http://x/og/verify"), ctx("WYP2C35185CQF7K3"))).status).toBe(404);
    expect((await verifyCard(new Request("http://x/og/verify"), ctx("nope"))).status).toBe(404);
    expect(lookup).toHaveBeenCalledTimes(1);
  });
});
