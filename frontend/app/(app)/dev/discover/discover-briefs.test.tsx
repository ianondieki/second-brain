import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { BRIEF_ID, discoverBrief } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";

import { BriefRow } from "./BriefRow";
import { ViewSwitch } from "./DiscoverControls";
import { DiscoverList } from "./DiscoverList";
import { discoverHref, parseDiscover, startProposalHref, VIEWS } from "./discover";

// REQ-DIR-05 (docs/spec/06 6.2, 6.5; docs/spec/07 items 1, 2, 4): Discover's Briefs view lists verified organisations'
// open Problem Briefs as cards (title, "Posted by <organisation>", niche and county, budget band and deadline on one
// line, statement, proposals, "Start a proposal from this brief" with the organisation named for the pitch).

afterEach(cleanup);

const COUNTIES = [{ code: "KE-30", name: "Nairobi City" }];

describe("the Briefs view's address", () => {
  it("is a fourth view, after the opportunity gap", () => {
    expect(VIEWS).toEqual(["problems", "projects", "gap", "briefs"]);
    expect(parseDiscover({ view: "briefs", county: "KE-30" })).toEqual({ view: "briefs", county: "KE-30" });
    expect(discoverHref({ view: "briefs", niche: "ict" })).toBe("/dev/discover?view=briefs&niche=ict");
  });

  it("starts a proposal with the problem linked (the pitch finds the organisation from it)", () => {
    expect(startProposalHref(BRIEF_ID)).toBe(`/dev/ideas/new?problem=${BRIEF_ID}`);
  });

  it("is a tab of the Lists navigation", () => {
    renderWithIntl(<ViewSwitch query={{ view: "briefs" }} />);
    const nav = screen.getByRole("navigation", { name: "Lists" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Problems",
      "Projects",
      "Gap",
      "Briefs",
    ]);
    expect(within(nav).getByRole("link", { name: "Briefs" }).getAttribute("aria-current")).toBe("page");
  });
});

// e2e/navigation.spec.ts: the Discover tabs fit 360 px without sideways scroll. The three tabs before this view
// ("Problems", "Projects", "Opportunity gap": 31 letters) fitted; the four now take no more letters in either language,
// and none is longer than the longest of the five developer tabs, which share the 360 px tab bar.
describe("the Discover tabs at 360 px", () => {
  const BUDGET = "ProblemsProjectsOpportunity gap".length;
  it.each([
    ["en", en],
    ["sw", sw],
  ] as const)("keep their %s labels within the three tabs' letters", (_, messages) => {
    const labels = VIEWS.map((view) => messages.discover.views[view]);
    expect(labels.reduce((sum, label) => sum + label.length, 0)).toBeLessThanOrEqual(BUDGET);
    const devLongest = Math.max(
      ...(["home", "discover", "ideas", "engagements", "companies"] as const).map((key) => messages.nav[key].length),
    );
    for (const label of labels) expect(label.length, label).toBeLessThanOrEqual(devLongest);
  });
});

describe("a Brief on Discover", () => {
  it("shows its organisation, place, terms, statement and proposals, with one chip and the way to start", () => {
    renderWithIntl(<BriefRow item={discoverBrief()} counties={COUNTIES} />);
    const card = screen.getByRole("article");
    expect(within(card).getByRole("link", { name: "Tower sites go dark when fuel runs out" }).getAttribute("href")).toBe(
      `/problems/${BRIEF_ID}`,
    );
    const badges = card.querySelectorAll("[data-label]");
    expect(badges).toHaveLength(1); // docs/spec/07 item 2: at most two
    expect(badges[0].textContent).toBe("Posted by Telco A (fixture)");
    expect(within(card).getByText("ICT › Networks & Telecommunications")).toBeTruthy();
    expect(within(card).getByText("Nairobi City")).toBeTruthy();
    expect(card.querySelector("[data-brief-terms]")?.textContent).toBe("Budget: KES 100,000 – 1,000,000Proposals by 30 Nov 2026");
    expect(within(card).getByText(/Field teams learn about empty generator tanks/)).toBeTruthy();
    expect(within(card).getByText("2 proposals")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Start a proposal from this brief" }).getAttribute("href")).toBe(
      `/dev/ideas/new?problem=${BRIEF_ID}`,
    );
    expect(card.querySelectorAll("[data-primary]")).toHaveLength(0); // the card's way in is a link, not the screen's primary
  });

  it("says when the organisation gave no band or deadline", () => {
    renderWithIntl(
      <BriefRow
        item={discoverBrief({ brief: { ...discoverBrief().brief, budget_band: null, deadline: null } })}
        counties={[]}
      />,
    );
    const terms = document.querySelector("[data-brief-terms]")!;
    expect(terms.textContent).toBe("Budget openNo deadline");
    expect(within(screen.getByRole("article")).getByText("Kenya")).toBeTruthy(); // no county list: the country
  });
});

describe("the Briefs list", () => {
  function emptyState() {
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    return {
      sentences: within(empty).getAllByRole("paragraph").map((p) => p.textContent),
      links: within(empty).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]),
    };
  }

  it("titles the view and lists the Briefs as cards", () => {
    renderWithIntl(
      <DiscoverList kind="briefs" briefs={{ items: [discoverBrief()], next_cursor: null }} query={{ view: "briefs" }} counties={COUNTIES} />,
    );
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(en.discover.briefsTitle);
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("is one sentence and one action when no Brief is open", () => {
    renderWithIntl(<DiscoverList kind="briefs" briefs={{ items: [], next_cursor: null }} query={{ view: "briefs" }} counties={COUNTIES} />);
    expect(emptyState()).toEqual({
      sentences: [en.discover.briefsEmpty],
      links: [[en.discover.toProblems, "/dev/discover"]],
    });
  });

  it("offers to clear the filters when they narrowed it", () => {
    renderWithIntl(
      <DiscoverList kind="briefs" briefs={{ items: [], next_cursor: null }} query={{ view: "briefs", county: "KE-30" }} counties={COUNTIES} />,
    );
    expect(emptyState()).toEqual({
      sentences: [en.discover.filteredEmpty],
      links: [[en.discover.clear, "/dev/discover?view=briefs"]],
    });
  });
});
