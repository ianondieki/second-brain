import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { CREDITED, NATIONWIDE, STRIP } from "@/lib/photos/photos";
import type { PublicExplore } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import CreditsPage from "../credits/page";
import { ExploreContent } from "./ExploreContent";

// P24 (REQ-UX-03; D-66): Explore, public. County tiles with their photographs, counts and anchors (the landing's strip
// links to them), the newest three titles under each as links, then the niches as rows; one primary action; when the
// summary cannot be read, one sentence and one action. Credits name every photograph the site shows.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => null }));

afterEach(cleanup);

const T = (id: string, title: string, niche: string | null = "Agriculture") => ({ id, title, niche, posted_at: "2026-10-07T07:00:00Z" });
const EXPLORE: PublicExplore = {
  seeded: true,
  totals: { problems: 7, counties: 2, niches: 2 },
  counties: [
    { code: "047", name: "Nairobi", count: 4, newest: [T("p1", "Late diesel deliveries", "ICT"), T("p2", "SACCO cyber security"), T("p3", "Clinic claims"), T("p4", "Fourth, not shown")] },
    { code: "016", name: "Machakos", count: 1, newest: [T("p5", "Mango spoilage")] },
  ],
  niches: [
    { id: "n1", name: "Agriculture", count: 3, newest: [T("p2", "SACCO cyber security")] },
    { id: "n2", name: "ICT", count: 2, newest: [T("p1", "Late diesel deliveries", "ICT")] },
  ],
};

async function explore(data: PublicExplore | null) {
  return renderWithIntl(<>{await resolveServerTree(<ExploreContent explore={data} />)}</>);
}

describe("Explore", () => {
  it("shows the counties as anchored tiles with their counts and newest three, then the niches", async () => {
    const { container } = await explore(EXPLORE);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Problems across Kenya");
    expect(container.querySelector("[data-explore='totals']")!.textContent).toBe("7 problems in 2 counties and 2 nichesSeeded example");
    const nairobi = container.querySelector<HTMLElement>("#nairobi")!;
    expect(within(nairobi).getByRole("heading", { level: 3 }).textContent).toBe("Nairobi");
    expect(nairobi.textContent).toContain("4 problems");
    const links = within(within(nairobi).getByRole("list", { name: "Newest in Nairobi" })).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/explore/problems/p1", "/explore/problems/p2", "/explore/problems/p3"]);
    // A photograph, decorative; the first one (a phone's first screen, the LCP) fetched at once, the rest lazily; tea
    // country where a county has none of its own.
    expect([nairobi.querySelector("img")!.getAttribute("loading"), nairobi.querySelector("img")!.getAttribute("fetchpriority")]).toEqual(["eager", "high"]);
    const machakos = container.querySelector<HTMLElement>("#machakos")!;
    expect(machakos.querySelector("img")!.getAttribute("src")).toBe(`/photos/${NATIONWIDE.slug}-800.webp`);
    expect(machakos.querySelector("img")!.getAttribute("loading")).toBe("lazy");
    expect(machakos.textContent).toContain("1 problem");
    // The two problems with no county (7 less the counties' 5) are the nationwide group, on tea country.
    const nationwide = container.querySelector<HTMLElement>("#nationwide")!;
    expect(within(nationwide).getByRole("heading", { level: 3 }).textContent).toBe("Nationwide");
    expect(nationwide.textContent).toContain("2 problems");
    const niches = screen.getByRole("heading", { level: 2, name: "By niche" }).parentElement!;
    expect(within(niches).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Agriculture", "ICT"]);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(container.querySelector("[data-primary]")!.textContent).toBe("Create an account");
  });

  it("leaves out the seeded label and the nationwide group when there is nothing for them", async () => {
    const { container } = await explore({ ...EXPLORE, seeded: false, totals: { ...EXPLORE.totals, problems: 5 } });
    expect(container.querySelector(".demo-label")).toBeNull();
    expect(container.querySelector("#nationwide")).toBeNull();
  });

  it("says one sentence with one way back when the summary cannot be read", async () => {
    const { container } = await explore(null);
    const empty = container.querySelector<HTMLElement>("[data-explore='empty']")!;
    expect(empty.textContent).toContain("Explore cannot load the published problems right now.");
    expect(within(empty).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["Back to the home page", "/"]]);
    expect(container.querySelector("[data-explore='totals']")).toBeNull();
    expect(screen.queryByRole("heading", { name: "By county" })).toBeNull();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("anchors every county of the landing's strip by the same name", async () => {
    const { container } = await explore({ ...EXPLORE, counties: STRIP.map((p, i) => ({ code: String(i), name: p.county, count: 1, newest: [] })) });
    expect(container.querySelector("#nationwide")).not.toBeNull();
    for (const photo of STRIP) expect(container.querySelector(`#${photo.county.toLowerCase().replace(/ /g, "-")}`), photo.county).not.toBeNull();
  });
});

describe("Credits", () => {
  it("credits every photograph the site shows with its attribution line", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(await CreditsPage())}</>);
    const items = [...container.querySelectorAll("[data-credits='photos'] li")];
    expect(items).toHaveLength(CREDITED.length);
    for (const photo of [...STRIP, ...CREDITED]) expect(container.textContent).toContain(photo.credit);
    for (const item of items) expect(item.textContent).toMatch(/via Wikimedia Commons/);
  });
});
