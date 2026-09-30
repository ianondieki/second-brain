import { describe, expect, it } from "vitest";

import { stateWithProblem } from "../ideas/versions";
import {
  cardChips,
  countryName,
  countyName,
  discoverHref,
  formatSourceDate,
  isColdStart,
  isNarrowed,
  moreWhy,
  nicheOptions,
  parseDiscover,
  problemHref,
  projectsById,
  PROFILING_HREF,
  sourceUrl,
  startProposalHref,
  trendQuery,
  type NicheNode,
  type TrendingProject,
} from "./discover";
import { nichesRefusal, countIssue, profilingRefusal, sameIds, toggle } from "./niches/picker";
import { recommendation, recommendations as answer } from "@/test/discover";

import { HOME_RECOMMENDATIONS, leadWhy, recommendationsState } from "./recommendations";

// REQ-TREND-02, REQ-PERS-01, REQ-PERS-03 (P12-F): the pure rules behind Discover, "Recommended for you" and the
// liked-niches picker. docs/spec/06 6.6 (cold start, badges), 6.7 (pursuit chip, Why chips) and docs/spec/07 item 2
// (at most two chips per card).

const TREND_BADGE = "Trending in ICT › Networks & Telecommunications · Kenya: 4 companies scouting, 1 new proposal";

describe("Discover's address", () => {
  it("reads the view, niche and county, dropping anything the API would refuse", () => {
    expect(parseDiscover({})).toEqual({ view: "problems" });
    expect(parseDiscover({ view: "gap", niche: "networks-telecommunications", county: "KE-30" })).toEqual({
      view: "gap",
      niche: "networks-telecommunications",
      county: "KE-30",
    });
    expect(parseDiscover({ view: "board", niche: "Bad Slug!", county: "Nairobi" })).toEqual({ view: "problems" });
    expect(parseDiscover({ view: ["projects", "gap"], niche: "a".repeat(81) })).toEqual({ view: "projects" });
  });

  it("leaves out the default view and empty filters, and keeps the filters across views", () => {
    expect(discoverHref()).toBe("/dev/discover");
    expect(discoverHref({ view: "problems" })).toBe("/dev/discover");
    expect(discoverHref({ view: "projects", niche: "health", county: "KE-01" })).toBe(
      "/dev/discover?view=projects&niche=health&county=KE-01",
    );
    expect(isNarrowed({ view: "gap" })).toBe(false);
    expect(isNarrowed({ view: "gap", county: "KE-01" })).toBe(true);
    expect(trendQuery({ view: "projects", niche: "health" })).toEqual({ niche: "health", county: undefined });
  });

  it("links the problem card, a new proposal from the problem and the profiling setting", () => {
    expect(problemHref("01a0f067-b61f-7121-8f83-4293f5a2c7cd")).toBe("/problems/01a0f067-b61f-7121-8f83-4293f5a2c7cd");
    expect(problemHref("a/b")).toBe("/problems/a%2Fb");
    expect(startProposalHref("01a0f067-b61f-7121-8f83-4293f5a2c7cd")).toBe(
      "/dev/ideas/new?problem=01a0f067-b61f-7121-8f83-4293f5a2c7cd",
    );
    expect(PROFILING_HREF).toBe("/dev/discover/niches#profiling");
  });
});

describe("a card's chips", () => {
  const why = ["4 companies scouting", "1 new proposal this month", "New this week"];

  it("shows at most two, and one beside a trend badge that already says the rest", () => {
    expect(cardChips({ trending: true, badge: TREND_BADGE }, why)).toEqual(["1 new proposal this month"]);
    expect(moreWhy({ trending: true, badge: TREND_BADGE }, why)).toEqual(["4 companies scouting", "New this week"]);
    expect(cardChips({ trending: false, badge: null }, why)).toEqual(["4 companies scouting", "1 new proposal this month"]);
    expect(moreWhy({ trending: false, badge: null }, why)).toEqual(["New this week"]);
    expect(cardChips({ trending: false, badge: null }, [])).toEqual([]);
  });

  it("ignores a badge on an item that does not trend (the API sends none; cold start hides it)", () => {
    expect(cardChips({ trending: false, badge: TREND_BADGE }, why)).toHaveLength(2);
  });

  it("is cold start when nothing in a non-empty list trends", () => {
    expect(isColdStart([])).toBe(false);
    expect(isColdStart([{ trend: { trending: false } }, { trend: { trending: false } }])).toBe(true);
    expect(isColdStart([{ trend: { trending: false } }, { trend: { trending: true } }])).toBe(false);
  });
});

describe("sources and places", () => {
  it("links only web addresses without credentials", () => {
    expect(sourceUrl("https://www.standardmedia.co.ke/health/article")).toBe("https://www.standardmedia.co.ke/health/article");
    expect(sourceUrl("javascript:alert(1)")).toBeNull();
    expect(sourceUrl("https://user:pw@example.com/")).toBeNull();
    expect(sourceUrl("not a url")).toBeNull();
  });

  it("dates a source by its calendar day, whatever the time zone", () => {
    expect(formatSourceDate("2026-09-28", "en")).toBe("28 Sept 2026");
    expect(formatSourceDate(null, "en")).toBeNull();
    expect(formatSourceDate("28/09/2026", "en")).toBeNull();
  });

  it("names the county when known, else the country", () => {
    const counties = [{ code: "KE-30", name: "Nairobi City" }];
    expect(countyName("KE-30", counties)).toBe("Nairobi City");
    expect(countyName("KE-01", counties)).toBeNull();
    expect(countyName(null, counties)).toBeNull();
    expect(countryName("KE", "en")).toBe("Kenya");
  });
});

describe("niches and projects", () => {
  const tree: NicheNode[] = [
    { id: "p1", slug: "ict", name: "ICT", label: "ICT", isic_code: null, children: [
      { id: "c1", slug: "networks-telecommunications", name: "Networks & Telecommunications", label: "ICT › Networks & Telecommunications", isic_code: null },
    ] },
    { id: "p2", slug: "health", name: "Health", label: "Health", isic_code: null, children: [] },
  ];

  it("flattens the tree, parents first", () => {
    expect(nicheOptions(tree)).toEqual([
      { id: "p1", slug: "ict", name: "ICT" },
      { id: "c1", slug: "networks-telecommunications", name: "Networks & Telecommunications", parent: "ICT" },
      { id: "p2", slug: "health", name: "Health" },
    ]);
  });

  it("finds a problem's projects by id", () => {
    const project = { proposal: { id: "x" } } as TrendingProject;
    expect(projectsById([project]).get("x")).toBe(project);
  });

  it("starts a new idea with the problem linked and its niche chosen, nothing else filled", () => {
    const problem = {
      id: "01a0f067-b61f-7121-8f83-4293f5a2c7cd",
      title: "Tower sites go down when generators run dry",
      source: "developer" as const,
      label: "Developer-reported",
      niche: { id: "c1", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" },
    };
    const state = stateWithProblem(problem);
    expect(state.problemMode).toBe("pick");
    expect(state.problems).toEqual([problem]);
    expect(state.nicheId).toBe("c1");
    expect(state.title).toBe("");
    expect(stateWithProblem({ ...problem, niche: null }).nicheId).toBe("");
  });
});

describe("the liked-niches picker", () => {
  it("holds 3 to 5", () => {
    expect(countIssue(0, 3, 5)).toBe("tooFew");
    expect(countIssue(2, 3, 5)).toBe("tooFew");
    expect(countIssue(3, 3, 5)).toBeNull();
    expect(countIssue(5, 3, 5)).toBeNull();
    expect(countIssue(6, 3, 5)).toBe("tooMany");
  });

  it("words the API's refusals as fixed sentences", () => {
    expect(nichesRefusal(422, { detail: { code: "liked_niches_count", message: "Choose 3 to 5 niches you like." } })).toBe("count");
    expect(nichesRefusal(422, { detail: { code: "unknown_niche", message: "x", niches: ["y"] } })).toBe("unknown");
    expect(nichesRefusal(422, { detail: [{ loc: ["body", "liked", 0], msg: "bad uuid", type: "uuid" }] })).toBe("failed");
    expect(nichesRefusal(404, { detail: { code: "not_found" } })).toBe("noProfile");
    expect(nichesRefusal(401, undefined)).toBe("signedOut");
    expect(nichesRefusal(429, undefined)).toBe("rateLimited");
    expect(nichesRefusal(0, undefined)).toBe("network");
    expect(nichesRefusal(500, "oops")).toBe("failed");
    expect(profilingRefusal(409, { detail: { code: "consent_text_changed" } })).toBe("changed");
    expect(profilingRefusal(409, { detail: { code: "other" } })).toBe("failed");
    expect(profilingRefusal(0, undefined)).toBe("network");
  });

  it("toggles ids in order and compares lists as sets", () => {
    expect(toggle(["a", "b"], "c")).toEqual(["a", "b", "c"]);
    expect(toggle(["a", "b", "c"], "b")).toEqual(["a", "c"]);
    expect(sameIds(["a", "b"], ["b", "a"])).toBe(true);
    expect(sameIds(["a", "b"], ["a"])).toBe(false);
    expect(sameIds(["a", "b"], ["a", "c"])).toBe(false);
  });
});

describe("Home's recommendations", () => {
  it("prompts for niches when there are none, and is unavailable without an answer", () => {
    expect(recommendationsState(null)).toEqual({ kind: "unavailable" });
    expect(recommendationsState(answer({ liked_niches: [] }))).toEqual({ kind: "noNiches" });
    expect(recommendationsState(answer({ items: [] }))).toEqual({ kind: "empty", personalised: false });
  });

  it("shows the first few in the ranker's order", () => {
    const items = [5, 2, 4, 1, 3].map((position) =>
      recommendation({ position, problem: { ...recommendation().problem, id: `p${position}` } }),
    );
    const state = recommendationsState(answer({ items, personalised: true }));
    expect(state.kind).toBe("list");
    if (state.kind !== "list") return;
    expect(state.items.map((item) => item.position)).toEqual([1, 2, 3]);
    expect(state.items).toHaveLength(HOME_RECOMMENDATIONS);
    expect(state.more).toBe(true);
    expect(state.personalised).toBe(true);
  });

  it("takes the first Why chip for the card", () => {
    expect(leadWhy(recommendation())).toBe("In a niche you like");
    expect(leadWhy(recommendation({ why: [] }))).toBeNull();
  });
});
