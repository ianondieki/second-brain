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
    // As the API names them: the reference data's names and codes (backend/seed/reference.yaml).
    { code: "KE-30", name: "Nairobi City", count: 4, newest: [T("p1", "Late diesel deliveries", "ICT"), T("p2", "SACCO cyber security"), T("p3", "Clinic claims"), T("p4", "Fourth, not shown")] },
    { code: "KE-22", name: "Machakos", count: 1, newest: [T("p5", "Mango spoilage")] },
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
    expect(container.querySelector("[data-explore='totals']")!.textContent).toBe("7 problems across 2 counties with problems and 2 nichesSeeded example");
    const nairobi = container.querySelector<HTMLElement>("[id='KE-30']")!;
    expect(within(nairobi).getByRole("heading", { level: 3 }).textContent).toBe("Nairobi City");
    expect(nairobi.textContent).toContain("4 problems");
    const links = within(within(nairobi).getByRole("list", { name: "Newest in Nairobi City" })).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/explore/problems/p1", "/explore/problems/p2", "/explore/problems/p3"]);
    // Nairobi's own photograph (keyed by its code, whatever the API calls it); the first one (a phone's first screen,
    // the LCP) fetched at once, the rest lazily.
    expect(nairobi.querySelector("img")!.getAttribute("src")).toBe("/photos/nairobi-golden-hour-800.webp");
    expect([nairobi.querySelector("img")!.getAttribute("loading"), nairobi.querySelector("img")!.getAttribute("fetchpriority")]).toEqual(["eager", "high"]);
    // A county with no photograph of its own is the night band with the lattice, never another place's photograph.
    const machakos = container.querySelector<HTMLElement>("[id='KE-22']")!;
    expect(machakos.querySelector("img")).toBeNull();
    expect(machakos.querySelector("[data-lattice]")).not.toBeNull();
    expect(machakos.textContent).toContain("1 problem");
    // The strip's counties the API left out are there too, with their photographs and no problem yet.
    const nakuru = container.querySelector<HTMLElement>("[id='KE-31']")!;
    expect(within(nakuru).getByRole("heading", { level: 3 }).textContent).toBe("Nakuru");
    expect(nakuru.textContent).toContain("0 problems");
    expect(nakuru.textContent).toContain("No public problems here yet.");
    expect(nakuru.querySelector("img")!.getAttribute("src")).toBe("/photos/nakuru-lake-800.webp");
    // The two problems with no county (7 less the counties' 5) are the nationwide group, on tea country.
    const nationwide = container.querySelector<HTMLElement>("#nationwide")!;
    expect(within(nationwide).getByRole("heading", { level: 3 }).textContent).toBe("Nationwide");
    expect(nationwide.querySelector("img")!.getAttribute("src")).toBe(`/photos/${NATIONWIDE.slug}-800.webp`);
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

  it("has a tile at every anchor the landing's strip links to, even with no problems", async () => {
    const { container } = await explore({ ...EXPLORE, counties: [], totals: { problems: 0, counties: 0, niches: 2 } });
    for (const county of STRIP) expect(container.querySelector(`[id='${county.code}']`), county.name).not.toBeNull();
    expect(container.querySelector("#nationwide")).toBeNull();
  });
});

describe("Credits", () => {
  it("credits every photograph the site shows: its title linked to its file page, the author, the licence linked, the change", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(await CreditsPage())}</>);
    const items = [...container.querySelectorAll("[data-credits='photos'] li")];
    expect(items).toHaveLength(CREDITED.length);
    for (const photo of [...STRIP.map((c) => c.photo), NATIONWIDE]) expect(CREDITED).toContain(photo);
    for (const photo of CREDITED) {
      const line = container.querySelector<HTMLElement>(`[data-credit='${photo.slug}']`)!;
      const work = within(line).getByRole("link", { name: photo.title });
      expect(work.getAttribute("href")).toBe(photo.source_url);
      expect(work.getAttribute("href")).toMatch(/^https:\/\/commons\.wikimedia\.org\/wiki\/File:/);
      expect(within(line).getByRole("link", { name: photo.licence }).getAttribute("href")).toBe(photo.licence_url);
      expect(line.textContent).toContain(`by ${photo.author}`);
      expect(line.textContent).toMatch(photo.slug === "kenya-tea" ? /cropped and resized/ : /; resized, via Wikimedia Commons\.$/);
    }
  });
});
