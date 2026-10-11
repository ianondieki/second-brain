import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { DirectoryFilters } from "./DirectoryFilters";
import { DirectoryResults } from "./DirectoryResults";
import {
  activeFilterCount,
  browseQuery,
  filtersHref,
  isOrgId,
  orgHref,
  parseFilters,
  splitNicheLabel,
  type DirectoryPage,
  type FilterOptions,
  type NicheNode,
  type OrgCard,
} from "./filters";
import { OrgProfile } from "./OrgProfile";
import { OrgTile } from "./OrgTile";

// REQ-DIR-01 (F1): Developer › Companies. docs/spec/06 6.2 (grouped by niche, org type and county filters; cards show
// name, niche, org type, county and the badge, never a logo) and docs/spec/07 items 2 and 4 (≤2 chips per card, empty
// states are one sentence and one action). P26: the list's cards and the company page in the portal's language.

afterEach(cleanup);

const E0_TEXT = "Listed from public information · not on the platform · not affiliated";
const E1_TEXT = "Domain verified (pending legal verification)";
const E2_TEXT = "Legal entity verified";
const TELECOMS = { id: "0199a000-0000-7000-8000-000000000001", slug: "networks", label: "ICT › Networks & Telecoms" };

function org(overrides: Partial<OrgCard> = {}): OrgCard {
  return {
    id: "0199a000-0000-7000-8000-0000000000aa",
    slug: "telkom-kenya",
    name: "Telkom Kenya Limited",
    kind: "company",
    niches: [TELECOMS],
    county: { code: "KE-30", name: "Nairobi City" },
    badge: { level: "e0", text: E0_TEXT },
    responsiveness: null,
    ...overrides,
  };
}

const PAGE: DirectoryPage = {
  groups: [
    {
      niche: TELECOMS,
      orgs: [
        org({
          id: "0199a000-0000-7000-8000-0000000000a1",
          name: "Airtel Networks Kenya Limited",
          badge: { level: "e2", text: E2_TEXT },
        }),
        org({
          id: "0199a000-0000-7000-8000-0000000000a2",
          name: "Afya Sacco",
          kind: "sacco_mfi",
          badge: { level: "e1", text: E1_TEXT },
        }),
        org(),
      ],
    },
    {
      niche: null,
      orgs: [org({ id: "0199a000-0000-7000-8000-0000000000a3", name: "Unsorted Org", niches: [], county: null })],
    },
  ],
  next_cursor: "next-cursor",
};

const NICHES: NicheNode[] = [
  {
    id: "n1",
    slug: "ict",
    name: "ICT",
    label: "ICT",
    isic_code: "J",
    children: [
      { id: "n2", slug: "networks", name: "Networks & Telecoms", label: "ICT › Networks & Telecoms", isic_code: "61" },
    ],
  },
  { id: "n3", slug: "public-sector", name: "Public sector", label: "Public sector", isic_code: "O", children: [] },
];
const OPTIONS: FilterOptions = {
  org_types: [
    { value: "company", label: "Company" },
    { value: "sacco_mfi", label: "SACCO or MFI" },
  ],
  counties: [
    { code: "KE-01", name: "Baringo" },
    { code: "KE-30", name: "Nairobi City" },
  ],
};

describe("filters from the URL", () => {
  it("keeps well-formed values and drops the rest", () => {
    expect(parseFilters({ q: "  telkom ", niche: "ict", kind: "company", county: "KE-30", cursor: "abc" })).toEqual({
      q: "telkom",
      niche: "ict",
      kind: "company",
      county: "KE-30",
      cursor: "abc",
    });
    expect(parseFilters({ q: "   ", niche: "ICT!", kind: "bank", county: "30", cursor: "x".repeat(2001) })).toEqual({});
    expect(parseFilters({ q: ["first", "second"], niche: ["a-b", "c"] })).toEqual({ q: "first", niche: "a-b" });
    expect(parseFilters({ q: "a\u0000b" }).q).toBe("ab");
    expect(parseFilters({ q: "x".repeat(150) }).q).toHaveLength(100);
  });

  it("cuts a long search at 100 characters without splitting an emoji", () => {
    const q = parseFilters({ q: `${"a".repeat(99)}😀😀` }).q!;
    expect(Array.from(q)).toHaveLength(100);
    expect(q.endsWith("😀")).toBe(true);
    expect(() => encodeURIComponent(q)).not.toThrow();
    expect(() => filtersHref({ q })).not.toThrow();
    expect(parseFilters({ q: "😀".repeat(150) }).q).toBe("😀".repeat(100));
  });

  it("builds links, the API query and the chosen-filter count", () => {
    expect(filtersHref({})).toBe("/dev/companies");
    expect(filtersHref({ q: "maji safi", county: "KE-30", cursor: "c1" })).toBe(
      "/dev/companies?q=maji+safi&county=KE-30&cursor=c1",
    );
    expect(browseQuery({ niche: "ict", kind: "sme" })).toEqual({
      q: undefined,
      niche: ["ict"],
      kind: ["sme"],
      county: undefined,
      cursor: undefined,
      limit: 30,
    });
    expect(activeFilterCount({ q: "x", niche: "ict", county: "KE-30" })).toBe(2);
  });

  it("links an organisation's page with the list's query, so its back link returns to the same list", () => {
    expect(orgHref("0199a000-0000-7000-8000-0000000000aa")).toBe("/dev/companies/0199a000-0000-7000-8000-0000000000aa");
    expect(orgHref("0199a000-0000-7000-8000-0000000000aa", { q: "tel", county: "KE-30", cursor: "c1" })).toBe(
      "/dev/companies/0199a000-0000-7000-8000-0000000000aa?q=tel&county=KE-30&cursor=c1",
    );
  });

  it("splits a two-level niche heading and checks organisation ids", () => {
    expect(splitNicheLabel("ICT › Networks & Telecoms")).toEqual({ parent: "ICT", name: "Networks & Telecoms" });
    expect(splitNicheLabel("Public sector")).toEqual({ name: "Public sector" });
    expect(isOrgId("0199a000-0000-7000-8000-0000000000aa")).toBe(true);
    expect(isOrgId("../../api/auth/me")).toBe(false);
  });
});

/** A photograph on the page that is not decoration (a logo would be one): an <img> with a non-empty alt. */
function meaningfulImages(container: HTMLElement) {
  return [...container.querySelectorAll("img")].filter((img) => (img.getAttribute("alt") ?? "") !== "");
}

function renderTile(card: OrgCard, groupNiche?: string) {
  return renderWithIntl(
    <ul>
      <OrgTile org={card} groupNiche={groupNiche} />
    </ul>,
  );
}

describe("OrgTile", () => {
  it("shows the place's band, the monogram, the name in the display face as its one link, type and county, and the badge verbatim as its only chip", () => {
    const { container } = renderTile(org());
    const card = container.querySelector("article[data-org='telkom-kenya']") as HTMLElement;
    const links = within(card).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("/dev/companies/0199a000-0000-7000-8000-0000000000aa");
    expect(links[0].textContent).toBe("Telkom Kenya Limited");
    const name = within(card).getByRole("heading", { level: 3, name: "Telkom Kenya Limited" });
    expect(name.className).toContain("font-display");
    expect(card.getAttribute("aria-labelledby")).toBe(name.id);
    // Nairobi has a county photograph: the band shows it, decorative (alt=""), never a logo.
    expect(card.querySelector("[data-niche-band]")?.getAttribute("data-niche-band")).toBe("nairobi-jacaranda");
    expect(card.querySelectorAll("img").length).toBeGreaterThan(0);
    expect(meaningfulImages(card)).toHaveLength(0);
    const seal = card.querySelector("[data-avatar='org']") as HTMLElement;
    expect(seal.textContent).toBe("TK");
    expect(seal.getAttribute("aria-hidden")).toBe("true");
    expect(card.querySelector("p")?.textContent).toBe("Company, Nairobi City"); // the meta line is the card's first line
    expect(screen.getByText(E0_TEXT)).toBeTruthy();
    expect(card.querySelectorAll("[data-badge]")).toHaveLength(1);
    expect(card.querySelectorAll("[data-chip]")).toHaveLength(0);
    expect(card.querySelector("[data-response]")).toBeNull();
  });

  it("takes the niche's photograph where the county has none, the section's niche where the organisation lists none, and the lattice last", () => {
    const { container } = renderTile(
      org({
        county: { code: "KE-01", name: "Baringo" },
        niches: [{ ...TELECOMS, slug: "networks-telecommunications" }],
      }),
    );
    expect(container.querySelector("[data-niche-band]")?.getAttribute("data-niche-band")).toBe(
      "longonot-earth-station",
    );
    cleanup();
    const unsorted = renderTile(org({ county: null, niches: [] }), "agriculture");
    expect(unsorted.container.querySelector("[data-niche-band]")?.getAttribute("data-niche-band")).toBe("kenya-tea");
    cleanup();
    const bare = renderTile(org({ county: null, niches: [] }));
    expect(bare.container.querySelector("[data-niche-band]")?.getAttribute("data-niche-band")).toBe("lattice");
    expect(bare.container.querySelector("img")).toBeNull();
  });

  it("shows the type alone without a county, and the response record only when the API sends one", () => {
    const { container } = renderTile(org({ county: null }));
    expect(container.querySelector("article p")?.textContent).toBe("Company");
    expect(screen.queryByText(/Usually answers/)).toBeNull();
    const text = "Usually answers in 4 days · 80% answered";
    cleanup();
    const answered = renderTile(
      org({ badge: { level: "e2", text: E2_TEXT }, responsiveness: { median_days: 4, answered_pct: 80, text } }),
    );
    expect(answered.container.querySelector("[data-response]")?.textContent).toBe(text);
    expect(answered.container.querySelector("[data-response] svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(answered.container.querySelectorAll("[data-badge]")).toHaveLength(1);
  });
});

function renderProfile(card: OrgCard, back = "/dev/companies?county=KE-30") {
  return renderWithIntl(<OrgProfile org={card} back={back} />);
}

describe("OrgProfile (the company page)", () => {
  it("opens on the county's photograph with the county named on it, then the monogram and the name as the page's title", () => {
    const { container } = renderProfile(org());
    const band = container.querySelector("[data-niche-band]") as HTMLElement;
    expect(band.getAttribute("data-niche-band")).toBe("nairobi-jacaranda");
    expect(band.textContent).toBe("Nairobi City");
    expect(band.className).toContain("niche-band-scrim"); // the night gradient under the words
    expect(meaningfulImages(container)).toHaveLength(0);
    expect(container.querySelector("[data-avatar='org']")?.className).toContain("size-20");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Telkom Kenya Limited");
    expect(screen.getByText("Company, Nairobi City")).toBeTruthy();
    expect(screen.getByRole("link", { name: "All companies" }).getAttribute("href")).toBe(
      "/dev/companies?county=KE-30",
    );
  });

  it("says what pitching an E0 organisation means in the held-tag sentence, and shows the badge verbatim", () => {
    const { container } = renderProfile(org());
    expect(screen.getByText(E0_TEXT)).toBeTruthy();
    expect(container.querySelectorAll("[data-badge]")).toHaveLength(1);
    expect(container.querySelector("[data-held]")?.textContent).toBe(
      "Telkom Kenya Limited isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify. We don't email them on your behalf.",
    );
    cleanup();
    const verified = renderProfile(org({ badge: { level: "e2", text: E2_TEXT } }));
    expect(verified.container.querySelector("[data-held]")).toBeNull();
    expect(screen.getByText(E2_TEXT)).toBeTruthy();
  });

  it("has one primary action, problems in its first niche on Discover, and a way to pitch one of your ideas", () => {
    const { container } = renderProfile(
      org({
        niches: [
          TELECOMS,
          { id: "n9", slug: "microfinance-saccos", label: "Financial services › Microfinance & SACCOs" },
        ],
      }),
    );
    const primary = container.querySelectorAll("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Find problems in Networks & Telecoms");
    expect(primary[0].getAttribute("href")).toBe("/dev/discover?niche=networks");
    expect(screen.getByRole("link", { name: "Pitch one of your ideas" }).getAttribute("href")).toBe("/dev/ideas");
    // The niches as links to Discover under their own heading.
    const niches = screen.getByRole("region", { name: "Problems in their niches" });
    expect(
      within(niches)
        .getAllByRole("link")
        .map((a) => [a.textContent, a.getAttribute("href")]),
    ).toEqual([
      ["ICT › Networks & Telecoms", "/dev/discover?niche=networks"],
      ["Financial services › Microfinance & SACCOs", "/dev/discover?niche=microfinance-saccos"],
    ]);
  });

  it("hides the primary action and the niches without a niche; the photograph falls back to the lattice", () => {
    const { container } = renderProfile(org({ niches: [], county: null }));
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Problems in their niches" })).toBeNull();
    const band = container.querySelector("[data-niche-band]") as HTMLElement;
    expect(band.getAttribute("data-niche-band")).toBe("lattice");
    expect(band.textContent).toBe("");
    expect(screen.getByRole("link", { name: "Pitch one of your ideas" })).toBeTruthy();
  });

  it("sets the facts as tiles: type, county and, only when sent, the response record's figures over the API's sentence", () => {
    const { container } = renderProfile(org());
    const facts = container.querySelector("dl[data-facts]") as HTMLElement;
    expect([...facts.querySelectorAll("dt")].map((dt) => dt.textContent)).toEqual(["Organisation type", "County"]);
    expect([...facts.querySelectorAll("dd")].map((dd) => dd.textContent)).toEqual(["Company", "Nairobi City"]);
    cleanup();
    const text = "Usually answers in 4 days · 80% answered";
    const answered = renderProfile(
      org({
        county: null,
        badge: { level: "e2", text: E2_TEXT },
        responsiveness: { median_days: 4, answered_pct: 80, text },
      }),
    );
    const tiles = answered.container.querySelector("dl[data-facts]") as HTMLElement;
    expect([...tiles.querySelectorAll("dt")].map((dt) => dt.textContent)).toEqual([
      "Organisation type",
      "County",
      "Response record",
    ]);
    const [, county, response] = [...tiles.querySelectorAll("dd")];
    expect(county.textContent).toBe("Not given");
    expect(response.querySelector(".font-figure")?.textContent).toBe("4 days · 80%");
    expect(response.textContent).toContain(text);
    cleanup();
    renderProfile(org({ responsiveness: { median_days: 1, answered_pct: 100, text } }));
    expect(screen.getByText("1 day · 100%")).toBeTruthy();
  });
});

describe("DirectoryResults", () => {
  it("groups organisations under niche headings, the unsorted ones last, with at most two chips each", () => {
    const { container } = renderWithIntl(<DirectoryResults kind="page" page={PAGE} filters={{}} />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["ICT › Networks & Telecoms", "Not yet sorted by niche"]); // one line, no label above
    expect(screen.getByText("3 organisations")).toBeTruthy();
    expect(screen.getByText("1 organisation")).toBeTruthy();
    // Each niche's organisations as a grid of cards, each card a list item; never a logo.
    const telecoms = screen.getByRole("region", { name: "ICT › Networks & Telecoms" });
    expect(within(telecoms).getAllByRole("listitem")).toHaveLength(3);
    expect(meaningfulImages(container)).toHaveLength(0);
    const rows = container.querySelectorAll("article");
    expect(rows).toHaveLength(4);
    for (const row of rows) expect(row.querySelectorAll("[data-badge]").length).toBeLessThanOrEqual(2);
    expect([...container.querySelectorAll("[data-badge]")].map((b) => b.getAttribute("data-badge"))).toEqual([
      "e2",
      "e1",
      "e0",
      "e0",
    ]);
    expect(screen.getByText(E2_TEXT)).toBeTruthy();
    expect(screen.getByText(E1_TEXT)).toBeTruthy();
  });

  it("links each organisation with the list's filters and page", () => {
    renderWithIntl(<DirectoryResults kind="page" page={PAGE} filters={{ county: "KE-30", cursor: "c1" }} />);
    expect(screen.getByRole("link", { name: "Telkom Kenya Limited" }).getAttribute("href")).toBe(
      "/dev/companies/0199a000-0000-7000-8000-0000000000aa?county=KE-30&cursor=c1",
    );
  });

  it("pages forward with the filters kept, and back to the first page from a later one", () => {
    renderWithIntl(<DirectoryResults kind="page" page={PAGE} filters={{ county: "KE-30" }} />);
    const pages = screen.getByRole("navigation", { name: "Pages" });
    expect(within(pages).getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      "/dev/companies?county=KE-30&cursor=next-cursor",
    );
    expect(within(pages).queryByRole("link", { name: "First page" })).toBeNull();
    cleanup();
    renderWithIntl(
      <DirectoryResults kind="page" page={{ ...PAGE, next_cursor: null }} filters={{ county: "KE-30", cursor: "c" }} />,
    );
    expect(screen.getByRole("link", { name: "First page" }).getAttribute("href")).toBe("/dev/companies?county=KE-30");
    expect(screen.queryByRole("link", { name: "Next page" })).toBeNull();
  });

  it.each([
    ["a narrowed search", { q: "zzz" }, "No organisations match these filters.", "Clear filters", "/dev/companies"],
    ["an empty directory", {}, "No organisations are listed yet.", "Go to Home", "/dev"],
    [
      "a page past the end",
      { cursor: "c" },
      "The list changed after this page loaded.",
      "First page",
      "/dev/companies",
    ],
  ])("shows one sentence and one action for %s", (_, filters, sentence, action, href) => {
    const { container } = renderWithIntl(
      <DirectoryResults kind="page" page={{ groups: [], next_cursor: null }} filters={filters} />,
    );
    const empty = container.querySelector("[data-empty-state]") as HTMLElement;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.querySelector("p")?.textContent).toBe(sentence);
    const links = within(empty).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0].textContent).toBe(action);
    expect(links[0].getAttribute("href")).toBe(href);
  });

  it("says a stale cursor is stale", () => {
    renderWithIntl(<DirectoryResults kind="staleCursor" filters={{ q: "x", cursor: "old" }} />);
    expect(screen.getByText("The list changed after this page loaded.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "First page" }).getAttribute("href")).toBe("/dev/companies?q=x");
  });
});

describe("DirectoryFilters", () => {
  it("is a GET search form with one primary action and the API's niches, types and counties", () => {
    const { container } = renderWithIntl(<DirectoryFilters filters={{}} niches={NICHES} options={OPTIONS} />);
    const form = container.querySelector("form") as HTMLFormElement;
    expect(form.getAttribute("method")).toBe("get");
    expect(form.getAttribute("action")).toBe("/dev/companies");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Show companies" }).hasAttribute("data-primary")).toBe(true);
    const niche = screen.getByLabelText("Niche") as HTMLSelectElement;
    expect([...niche.options].map((o) => [o.value, o.textContent])).toEqual([
      ["", "All niches"],
      ["ict", "All of ICT"],
      ["networks", "Networks & Telecoms"],
      ["public-sector", "Public sector"],
    ]);
    const kind = screen.getByLabelText("Organisation type") as HTMLSelectElement;
    expect([...kind.options].map((o) => o.textContent)).toEqual([
      "All types",
      "Company",
      "SACCO or microfinance institution",
    ]);
    expect([...(screen.getByLabelText("County") as HTMLSelectElement).options].map((o) => o.value)).toEqual([
      "",
      "KE-01",
      "KE-30",
    ]);
    expect(container.querySelector("details")?.open).toBe(false);
    expect(screen.getByText("Filters")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
  });

  it("opens the filters when one is chosen, keeps the choices and offers to clear them", () => {
    const { container } = renderWithIntl(
      <DirectoryFilters filters={{ q: "tel", county: "KE-30" }} niches={NICHES} options={OPTIONS} />,
    );
    expect(container.querySelector("details")?.open).toBe(true);
    expect(screen.getByText("Filters (1 chosen)")).toBeTruthy();
    expect((screen.getByLabelText("County") as HTMLSelectElement).value).toBe("KE-30");
    expect((screen.getByLabelText("Search by name") as HTMLInputElement).value).toBe("tel");
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe("/dev/companies");
  });
});
