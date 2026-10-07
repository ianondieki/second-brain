// @vitest-environment node
import { createTranslator } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

// P24 (REQ-UX-04): the share cards. A published teaser and a found certificate answer a 1200 × 630 PNG; a draft or
// hidden idea, an unknown certificate and a malformed id answer 404 with no image.

const api = vi.hoisted(() => ({ GET: vi.fn() }));
const lookup = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ serverApi: () => api, forwardHeaders: async () => ({}) }));
vi.mock("@/app/(public)/verify/lookup", () => ({ lookupCertificate: lookup }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

const { GET: ideaCard } = await import("./idea/[id]/route");
const { GET: verifyCard } = await import("./verify/[id]/route");

const SEEDED = "0199b000-0000-7000-8000-0000000000aa";
const ctx = (id: string) => ({ params: Promise.resolve({ id }) }) as never;

async function isPng(response: Response) {
  const bytes = new Uint8Array(await response.arrayBuffer());
  return [...bytes.slice(0, 4)].join(",") === "137,80,78,71";
}

beforeEach(() => {
  api.GET.mockReset();
  lookup.mockReset();
});

describe("GET /og/idea/<id>", () => {
  it("draws the published teaser's title and niche as a PNG", async () => {
    api.GET.mockResolvedValue({ data: { teaser: { title: "Cold chain for dairy co-ops", niche: { id: "n", label: "Agriculture", slug: "agriculture" } } }, response: new Response(null, { status: 200 }) });
    const response = await ideaCard(new Request("http://x/og/idea"), ctx(SEEDED));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(await isPng(response)).toBe(true);
    expect(api.GET).toHaveBeenCalledWith("/api/proposals/{proposal_id}", expect.objectContaining({ params: { path: { proposal_id: SEEDED } } }));
  }, 30_000);

  it("answers 404 for a private idea (the API's 404) and for an id that is not one", async () => {
    api.GET.mockResolvedValue({ data: undefined, response: new Response(null, { status: 404 }) });
    const hidden = await ideaCard(new Request("http://x/og/idea"), ctx(SEEDED));
    expect(hidden.status).toBe(404);
    expect(hidden.headers.get("content-type")).toBeNull();
    const malformed = await ideaCard(new Request("http://x/og/idea"), ctx("../../api/me"));
    expect(malformed.status).toBe(404);
    expect(api.GET).toHaveBeenCalledTimes(1);
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
