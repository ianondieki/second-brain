import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { countyPhoto, countyPhotos, nichePhoto, topNiche } from "@/lib/photos/niche";
import { resolveServerTree } from "@/test/server-tree";

import { NicheBand } from "./NicheBand";

// D-67 (P25; REQ-UX-05): a niche's or a county's photograph as a narrow, decorative band beside a visible name; the
// lattice where there is none, and when the request carries Save-Data: on.

const request = vi.hoisted(() => ({ headers: new Headers() }));
// A request's headers as React's `use` reads a settled promise (NicheBand reads them synchronously).
vi.mock("next/headers", () => ({
  headers: () => Object.assign(Promise.resolve(request.headers), { status: "fulfilled", value: request.headers }),
}));

beforeEach(() => {
  request.headers = new Headers();
});
afterEach(cleanup);

async function band(props: Parameters<typeof NicheBand>[0]) {
  const { container } = render(<>{await resolveServerTree(<NicheBand {...props} />)}</>);
  return container.querySelector<HTMLElement>("[data-niche-band]")!;
}

describe("nichePhoto", () => {
  it("maps a niche at any level to its top-level niche", () => {
    expect(topNiche("microfinance-saccos")).toBe("financial-services");
    expect(topNiche("county-government")).toBe("public-sector");
    expect(topNiche("agriculture")).toBe("agriculture");
  });

  it("gives agriculture tea, logistics the ferry and retail the market until each niche has its own", () => {
    expect(nichePhoto({ niche: "agriculture" })?.slug).toBe("kenya-tea");
    expect(nichePhoto({ niche: "logistics" })?.slug).toBe("mombasa-likoni-ferry");
    expect(nichePhoto({ niche: "retail" })?.slug).toBe("rongai-market");
  });

  it("gives every top-level niche the photograph the index marks with it (P25-A), a child niche its parent's", () => {
    expect(nichePhoto({ niche: "networks-telecommunications" })?.slug).toBe("longonot-earth-station");
    expect(nichePhoto({ niche: "microfinance-saccos" })?.slug).toBe("nairobi-skyline");
    expect(nichePhoto({ niche: "county-government" })?.slug).toBe("nairobi-city-hall");
    expect(nichePhoto({ niche: "health" })?.slug).toBe("turkana-naipekarr-dispensary");
  });

  it("puts the county's photograph first where the county has one (a Kisumu county-government problem shows Kisumu)", () => {
    expect(nichePhoto({ niche: "county-government", county: "KE-17" })?.slug).toBe("kisumu-lake-victoria");
    expect(nichePhoto({ niche: "agriculture", county: "KE-31" })?.slug).toBe("nakuru-lake");
    expect(nichePhoto({ niche: "agriculture", county: "KE-99" })?.slug).toBe("kenya-tea");
  });

  it("puts only a county-role photograph ahead of the niche: another niche's photograph of that county never stands in", () => {
    // Turkana's only photograph is the health niche's dispensary; Kajiado's the retail niche's market.
    expect(nichePhoto({ niche: "agriculture", county: "KE-43" })?.slug).toBe("kenya-tea");
    expect(nichePhoto({ niche: "energy", county: "KE-10" })?.slug).toBe("ngong-hills-wind");
    expect(nichePhoto({ niche: "health", county: "KE-43" })?.slug).toBe("turkana-naipekarr-dispensary");
    expect(nichePhoto({ niche: "a-niche-added-later", county: "KE-43" })).toBeUndefined();
    // With no niche, any photograph of the county is the place.
    expect(nichePhoto({ county: "KE-43" })?.slug).toBe("turkana-naipekarr-dispensary");
  });

  it("gives a company with no niche its HQ county's photograph, the county role first", () => {
    expect(nichePhoto({ county: "KE-31" })?.slug).toBe("nakuru-lake");
    expect(countyPhoto("KE-30")?.slug).toBe("nairobi-jacaranda");
    expect(countyPhoto("KE-43")?.slug).toBe("turkana-naipekarr-dispensary");
    expect(countyPhoto("KE-99")).toBeUndefined();
  });

  it("lists a county's own photographs, the county role first, never a niche's photograph taken there (P26)", () => {
    expect(countyPhotos("KE-30").map((p) => p.slug)).toEqual([
      "nairobi-jacaranda",
      "nairobi-skyline",
      "nairobi-golden-hour",
      "nairobi-morning",
    ]);
    expect(countyPhotos("KE-31").map((p) => p.slug)).toEqual(["nakuru-lake"]);
    expect(countyPhotos("KE-10")).toEqual([]); // Kajiado: only the retail niche's market
    expect(countyPhotos("KE-99")).toEqual([]);
    expect(countyPhotos(null)).toEqual([]);
  });

  it("gives nothing where there is no fitting photograph (the lattice band)", () => {
    expect(nichePhoto({ niche: "a-niche-added-later" })).toBeUndefined();
    expect(nichePhoto({ county: "KE-99" })).toBeUndefined();
    expect(nichePhoto({})).toBeUndefined();
  });
});

describe("NicheBand", () => {
  it("crops a photograph where it is told (position), never the lattice or a Save-Data band", async () => {
    const top = await band({ county: "KE-30", position: "top" });
    expect(top.getAttribute("data-band-position")).toBe("top");
    expect(top.querySelector("img")?.className).toContain("object-[50%_20%]");
    const bottom = await band({ county: "KE-30", position: "bottom" });
    expect(bottom.getAttribute("data-band-position")).toBe("bottom");
    expect(bottom.querySelector("img")?.className).toContain("object-[50%_80%]");
    const plain = await band({ county: "KE-30" });
    expect(plain.hasAttribute("data-band-position")).toBe(false);
    expect(plain.querySelector("img")?.className).not.toContain("object-[");
    const lattice = await band({ niche: "a-niche-added-later", position: "center" });
    expect(lattice.getAttribute("data-niche-band")).toBe("lattice");
    expect(lattice.hasAttribute("data-band-position")).toBe(false);
    request.headers = new Headers({ "save-data": "on" });
    const saving = await band({ county: "KE-30", position: "center" });
    expect(saving.getAttribute("data-niche-band")).toBe("lattice");
    expect(saving.hasAttribute("data-band-position")).toBe(false);
    expect(saving.querySelector("img")).toBeNull();
  });

  it("shows the photograph a caller picks (null: the lattice), and drops it under Save-Data", async () => {
    expect((await band({ county: "KE-30", photo: "nairobi-skyline" })).getAttribute("data-niche-band")).toBe(
      "nairobi-skyline",
    );
    expect((await band({ county: "KE-30", photo: null })).getAttribute("data-niche-band")).toBe("lattice");
    request.headers = new Headers({ "save-data": "on" });
    expect((await band({ photo: "nairobi-skyline" })).getAttribute("data-niche-band")).toBe("lattice");
  });

  it("never shows a named organisation's premises on a band that stands for an organisation (a Brief: forOrganisation)", async () => {
    const slug = async (props: Parameters<typeof NicheBand>[0]) => (await band(props)).getAttribute("data-niche-band");
    // A Kiambu university's Brief: Education's photograph is Strathmore's campus, so the lattice; a problem keeps it.
    expect(await slug({ niche: "higher-education", county: "KE-22", forOrganisation: true })).toBe("lattice");
    expect(await slug({ niche: "higher-education", county: "KE-22" })).toBe("nairobi-strathmore-campus");
    for (const niche of ["ict", "public-sector", "health", "energy"]) {
      expect(await slug({ niche, county: "KE-22", forOrganisation: true })).toBe("lattice");
    }
    // No one's premises: the tea fields stay; a county with its own photographs shows them first.
    expect(await slug({ niche: "agriculture", county: "KE-22", forOrganisation: true })).toBe("kenya-tea");
    expect(await slug({ niche: "higher-education", county: "KE-30", forOrganisation: true })).toBe("nairobi-jacaranda");
  });

  it("fetches a hero band at once and at high priority (eager); a band is lazy and low otherwise", async () => {
    const hero = (await band({ county: "KE-30", eager: true, wide: true })).querySelector("img")!;
    expect(hero.getAttribute("loading")).toBe("eager");
    expect(hero.getAttribute("fetchpriority")).toBe("high");
    const card = (await band({ county: "KE-30" })).querySelector("img")!;
    expect(card.getAttribute("loading")).toBe("lazy");
    expect(card.getAttribute("fetchpriority")).toBe("low");
  });

  it("is a decorative picture (AVIF, then WebP) with its size, lazy and decoded off the main thread", async () => {
    const el = await band({ niche: "agriculture" });
    expect(el.dataset.nicheBand).toBe("kenya-tea");
    const img = el.querySelector("img")!;
    expect(img.getAttribute("alt")).toBe("");
    expect(img.getAttribute("loading")).toBe("lazy");
    expect(img.getAttribute("decoding")).toBe("async");
    expect(img.getAttribute("width")).toBeTruthy();
    expect(img.getAttribute("height")).toBeTruthy();
    expect(el.querySelector("source")?.getAttribute("type")).toBe("image/avif");
    // A band is a short strip: the 480 px card-band files (P25-A).
    expect(img.getAttribute("src")).toMatch(/kenya-tea-480\.webp$/);
    expect(img.getAttribute("srcset")).toBe("/photos/kenya-tea-480.webp 480w");
  });

  it("draws the lattice band where there is no photograph", async () => {
    const el = await band({ niche: "a-niche-added-later" });
    expect(el.dataset.nicheBand).toBe("lattice");
    expect(el.className).toContain("niche-band-lattice");
    expect(el.querySelector("img")).toBeNull();
  });

  it("sends no photograph when the request asks to save data", async () => {
    request.headers = new Headers({ "Save-Data": "on" });
    const el = await band({ niche: "agriculture" });
    expect(el.dataset.nicheBand).toBe("lattice");
    expect(el.querySelector("img, picture")).toBeNull();
  });

  it("puts the night gradient under text set on a photograph", async () => {
    const el = await band({ county: "KE-28", children: <span>Mombasa</span> });
    expect(el.className).toContain("niche-band-scrim");
    expect(el.textContent).toBe("Mombasa");
  });
});
