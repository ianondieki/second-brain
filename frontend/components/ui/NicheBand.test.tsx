import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { countyPhoto, nichePhoto, topNiche } from "@/lib/photos/niche";
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

  it("gives the public sector, and a company with no niche, its county's photograph", () => {
    expect(nichePhoto({ niche: "county-government", county: "KE-17" })?.slug).toBe("kisumu-lake-victoria");
    expect(nichePhoto({ niche: "public-sector", county: "KE-30" })?.county_code).toBe("KE-30");
    expect(nichePhoto({ county: "KE-31" })?.slug).toBe("nakuru-lake");
    expect(countyPhoto("KE-99")).toBeUndefined();
  });

  it("gives nothing where there is no fitting photograph (the lattice band)", () => {
    expect(nichePhoto({ niche: "health" })).toBeUndefined();
    expect(nichePhoto({ niche: "networks-telecommunications", county: "KE-30" })).toBeUndefined();
    expect(nichePhoto({ niche: "public-sector" })).toBeUndefined();
    expect(nichePhoto({})).toBeUndefined();
  });
});

describe("NicheBand", () => {
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
    expect(img.getAttribute("src")).toMatch(/\.webp$/);
  });

  it("draws the lattice band where there is no photograph", async () => {
    const el = await band({ niche: "energy" });
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
