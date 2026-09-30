import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import { BADGE, PROBLEM_ID, PROJECT_ID, recommendation, recommendations, trendingProblem, trendingProject } from "@/test/discover";

import { DiscoverList } from "./DiscoverList";
import type { TrendingOut } from "./discover";
import { NichePicker, type PickerNiche } from "./niches/NichePicker";
import { ProfilingToggle } from "./niches/ProfilingToggle";
import { ProblemRow } from "./ProblemRow";
import { ProjectRow } from "./ProjectRow";
import { RecommendedForYou } from "./RecommendedForYou";
import { recommendationsState } from "./recommendations";

// REQ-TREND-02, REQ-PERS-01, REQ-PERS-03 (P12-F): Discover's cards and lists, Home's "Recommended for you" and the
// liked-niches page. docs/spec/06 6.6 (badge only when trending, projects beside their problems: AC-TREND-2), 6.7
// (pursuit chip plus a Why chip: AC-PERS-2), docs/spec/07 items 2 and 4 (at most two chips; empty states are one
// sentence and one action).

afterEach(cleanup);

const COUNTIES = [{ code: "KE-30", name: "Nairobi City" }];
const board = (overrides: Partial<TrendingOut> = {}): TrendingOut => ({
  generated_at: "2026-09-30T06:42:45+03:00",
  problems: [trendingProblem()],
  projects: [trendingProject()],
  ...overrides,
});

function emptyState() {
  const empty = document.querySelector<HTMLElement>("[data-empty-state]");
  expect(empty).not.toBeNull();
  return {
    sentence: within(empty!).getAllByRole("paragraph").map((p) => p.textContent),
    links: within(empty!).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]),
  };
}

describe("a Discover problem", () => {
  it("shows its badge, links its card, keeps to two chips and offers to start a proposal", () => {
    renderWithIntl(<ProblemRow item={trendingProblem()} counties={COUNTIES} projects={[trendingProject()]} query={{ view: "problems" }} />);
    const card = screen.getByRole("article");
    expect(card.querySelector("[data-badge]")?.textContent).toBe(BADGE);
    expect(screen.getByRole("link", { name: "Tower sites go down when generators run dry" }).getAttribute("href")).toBe(
      `/problems/${PROBLEM_ID}`,
    );
    expect(card.querySelectorAll("[data-chip]")).toHaveLength(1); // the badge already says the rest
    expect(card.querySelector("[data-chip]")?.textContent).toBe("1 new proposal this month");
    expect(within(card).getByText("Kenya")).toBeTruthy();
    expect(within(card).getByText("1 proposal")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Start a proposal from this problem" }).getAttribute("href")).toBe(
      `/dev/ideas/new?problem=${PROBLEM_ID}`,
    );
  });

  it("lists the other chips, its sources and the projects solving it under the disclosure", () => {
    renderWithIntl(<ProblemRow item={trendingProblem()} counties={COUNTIES} projects={[trendingProject()]} query={{ view: "problems", niche: "ict" }} />);
    const more = screen.getByText("More about this problem").closest("details")!;
    expect(within(more).getByText("New this week")).toBeTruthy();
    expect(within(more).queryByText("4 companies scouting")).toBeNull(); // the badge says it already
    const source = within(more).getByRole("link", { name: "Communications Authority of Kenya" });
    expect(source.getAttribute("href")).toBe("https://www.ca.go.ke/report");
    expect(source.getAttribute("rel")).toContain("noopener");
    expect(within(more).getByText("Published 28 Sep 2026")).toBeTruthy(); // one date format (REQ-UX-07)
    expect(within(more).getByRole("link", { name: "Fuel-level alerts for off-grid tower sites" }).getAttribute("href")).toBe(
      `/dev/discover?view=projects&niche=ict#project-${PROJECT_ID}`,
    );
  });

  it("hides the badge while it does not trend, and names its county", () => {
    const item = trendingProblem({
      trend: { trending: false, new_this_week: true, z: null, score: 3, badge: null },
      why: ["2 new sources this month", "New this week"],
      sources: [],
      problem: { ...trendingProblem().problem, county_code: "KE-30" },
    });
    renderWithIntl(<ProblemRow item={item} counties={COUNTIES} query={{ view: "problems" }} />);
    const card = screen.getByRole("article");
    expect(card.querySelector("[data-badge]")).toBeNull();
    expect(card.hasAttribute("data-trending")).toBe(false);
    expect([...card.querySelectorAll("[data-chip]")].map((chip) => chip.textContent)).toEqual([
      "2 new sources this month",
      "New this week",
    ]);
    expect(within(card).getByText("Nairobi City")).toBeTruthy();
    expect(within(card).getByText("No cited sources: a developer described this problem.")).toBeTruthy();
  });
});

describe("a Discover project", () => {
  it("renders the problem it solves beside it, linked to its card (AC-TREND-2)", () => {
    renderWithIntl(<ProjectRow item={trendingProject()} />);
    const card = screen.getByRole("article");
    const solves = card.querySelector<HTMLElement>(`[data-solves="${PROBLEM_ID}"]`)!;
    expect(within(solves).getByText("Solves")).toBeTruthy();
    const link = within(solves).getByRole("link", { name: "Tower sites go down when generators run dry" });
    expect(link.getAttribute("href")).toBe(`/problems/${PROBLEM_ID}`);
    expect(card.id).toBe(`project-${PROJECT_ID}`);
    expect(card.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    expect(card.textContent).not.toMatch(/\d+ (companies|organisations)/);
  });
});

describe("a Discover list", () => {
  it("titles trending problems, and cold start as new this week", () => {
    const { unmount } = renderWithIntl(<DiscoverList kind="board" board={board()} query={{ view: "problems" }} counties={COUNTIES} />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Trending problems");
    unmount();
    const cold = trendingProblem({ trend: { trending: false, new_this_week: true, z: null, score: 1, badge: null } });
    renderWithIntl(<DiscoverList kind="board" board={board({ problems: [cold] })} query={{ view: "problems" }} counties={COUNTIES} />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("New this week");
    expect(document.querySelector("[data-badge]")).toBeNull();
  });

  it("never shows more than 20", () => {
    const many = Array.from({ length: 25 }, (_, n) =>
      trendingProblem({ problem: { ...trendingProblem().problem, id: `p${n}` }, project_ids: [] }),
    );
    renderWithIntl(<DiscoverList kind="board" board={board({ problems: many })} query={{ view: "problems" }} counties={COUNTIES} />);
    expect(screen.getAllByRole("article")).toHaveLength(20);
  });

  it("is one sentence and one action when empty", () => {
    const { unmount } = renderWithIntl(
      <DiscoverList kind="board" board={board({ problems: [] })} query={{ view: "problems" }} counties={COUNTIES} />,
    );
    expect(emptyState()).toEqual({
      sentence: ["Nothing is trending or new yet."],
      links: [["Describe a problem you know", "/dev/ideas/new"]],
    });
    unmount();
    const narrowed = renderWithIntl(
      <DiscoverList kind="board" board={board({ projects: [] })} query={{ view: "projects", county: "KE-30" }} counties={COUNTIES} />,
    );
    expect(emptyState()).toEqual({
      sentence: ["Nothing here for this niche and county yet."],
      links: [["Clear filters", "/dev/discover?view=projects"]],
    });
    narrowed.unmount();
    renderWithIntl(
      <DiscoverList kind="gap" gap={{ generated_at: "2026-09-30T06:42:45+03:00", items: [] }} query={{ view: "gap" }} counties={COUNTIES} />,
    );
    expect(emptyState()).toEqual({
      sentence: ["No rising problem is short of proposals right now."],
      links: [["See trending problems", "/dev/discover"]],
    });
  });
});

describe("Recommended for you", () => {
  it("shows the pursuit chip and one Why chip on each card, and the reasons on demand (AC-PERS-2)", () => {
    renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations())} />);
    const card = screen.getByRole("article");
    const chips = [...card.querySelectorAll("[data-chip]")].map((chip) => chip.textContent);
    expect(chips).toEqual(["Pursue · Good fit", "In a niche you like"]);
    expect(within(card).getByRole("link", { name: /Clinics must move claims/ }).getAttribute("href")).toBe(
      "/problems/01a0f067-d873-7f06-941f-2e211f23caf3",
    );
    const more = within(card).getByText("Why this, and why not").closest("details")!;
    expect(within(more).getByRole("heading", { name: "Why “Pursue”" })).toBeTruthy();
    expect(within(more).getByText("Good fit for you")).toBeTruthy();
    expect(within(more).queryByRole("heading", { name: "Why not" })).toBeNull();
    expect(card.textContent).not.toMatch(/profit|revenue/i);
  });

  it("says what the ranking uses and links the setting", () => {
    const { unmount } = renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations())} />);
    const note = document.querySelector("[data-personalised]")!;
    expect(note.textContent).toBe("Ranked on your niches and county only, not your activity. Recommendation settings");
    expect(within(note as HTMLElement).getByRole("link").getAttribute("href")).toBe("/dev/discover/niches#profiling");
    unmount();
    renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations({ personalised: true }))} />);
    expect(document.querySelector("[data-personalised]")?.getAttribute("data-personalised")).toBe("on");
  });

  it("labels Not now and Consider, the exploration slot and the Why-not line", () => {
    const items = [
      recommendation({
        exploring: true,
        label: "Stretch",
        pursuit: { decision: "not_now", label: "Not now", reasons: ["A weak fit with your niches and county"] },
        why_not: "Outside your liked niches",
      }),
      recommendation({
        position: 2,
        problem: { ...recommendation().problem, id: "second" },
        pursuit: { decision: "consider", label: "Consider", reasons: ["No organisation demand yet"] },
      }),
    ];
    renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations({ items }))} />);
    const [first, second] = screen.getAllByRole("article");
    expect(first.querySelector("[data-chip=pursuit]")?.textContent).toBe("Not now · Stretch");
    expect(within(first).getByText("Exploring: outside your niches")).toBeTruthy();
    expect(within(first).getByText("Outside your liked niches")).toBeTruthy();
    expect(second.querySelector("[data-chip=pursuit]")?.textContent).toBe("Consider · Good fit");
  });

  it("prompts for niches, and is one sentence and one action when empty", () => {
    const { unmount } = renderWithIntl(<RecommendedForYou state={{ kind: "noNiches" }} />);
    expect(emptyState()).toEqual({
      sentence: ["Choose 3 to 5 niches you like to get problems recommended to you."],
      links: [["Choose your niches", "/dev/discover/niches"]],
    });
    unmount();
    renderWithIntl(<RecommendedForYou state={{ kind: "empty", personalised: false }} />);
    expect(emptyState()).toEqual({
      sentence: ["Nothing to recommend yet: new problems show on Discover first."],
      links: [["Open Discover", "/dev/discover"]],
    });
  });
});

const NICHES: PickerNiche[] = [
  { id: "agri", name: "Agriculture", children: [] },
  { id: "fin", name: "Financial services", children: [{ id: "mfi", name: "Microfinance & SACCOs" }] },
  { id: "health", name: "Health", children: [] },
  { id: "ict", name: "ICT", children: [{ id: "tel", name: "Networks & Telecommunications" }] },
];

function liked(ids: string[]) {
  return { liked: ids.map((id) => ({ id, slug: id, label: id })), min: 3, max: 5 };
}

describe("the liked-niches picker", () => {
  it("checks the count before sending, then saves the whole list", async () => {
    const saveImpl = vi.fn(async (ids: string[]) => ({ ok: true as const, value: liked(ids) }));
    renderWithIntl(<NichePicker niches={NICHES} initial={[]} min={3} max={5} saveImpl={saveImpl} />);
    expect(screen.getByText("0 of 5 chosen")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Health"));
    fireEvent.click(screen.getByLabelText("Microfinance & SACCOs"));
    fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
    expect(screen.getByText("Choose at least 3 niches.")).toBeTruthy();
    expect(saveImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Networks & Telecommunications"));
    expect(screen.queryByText("Choose at least 3 niches.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
    await waitFor(() => expect(screen.getByText("Saved. Your recommendations now use these niches.")).toBeTruthy());
    expect(saveImpl).toHaveBeenCalledWith(["health", "mfi", "tel"]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("refuses more than five, and never sends an empty list", async () => {
    const saveImpl = vi.fn();
    renderWithIntl(<NichePicker niches={NICHES} initial={["agri", "fin", "mfi", "health", "ict"]} min={3} max={5} saveImpl={saveImpl} />);
    fireEvent.click(screen.getByLabelText("Networks & Telecommunications"));
    fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
    expect(screen.getByText("Choose at most 5 niches.")).toBeTruthy();
    for (const id of ["Agriculture", "Financial services", "Microfinance & SACCOs", "Health", "ICT", "Networks & Telecommunications"]) {
      fireEvent.click(screen.getByLabelText(id));
    }
    fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
    expect(screen.getByText("Choose at least 3 niches.")).toBeTruthy();
    expect(saveImpl).not.toHaveBeenCalled();
  });

  it("words the API's refusals as fixed sentences", async () => {
    for (const [problem, sentence] of [
      ["count", "Choose 3 to 5 niches."],
      ["unknown", "One of these niches is no longer offered. Reload the page and choose again."],
    ] as const) {
      const saveImpl = vi.fn(async () => ({ ok: false as const, problem }));
      const { unmount } = renderWithIntl(<NichePicker niches={NICHES} initial={["agri", "fin", "health"]} min={3} max={5} saveImpl={saveImpl} />);
      fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
      await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(sentence));
      unmount();
    }
  });
});

describe("the profiling setting", () => {
  const consent = { granted: false, text: "Use my niches and activity to recommend problems.", version: "v1" };

  it("shows the API's wording and records the decision on its version", async () => {
    const setImpl = vi.fn(async (granted: boolean) => ({
      ok: true as const,
      value: { purpose: "profiling" as const, granted, text: consent.text, version: "v1" },
    }));
    renderWithIntl(<ProfilingToggle consent={consent} setImpl={setImpl} />);
    expect(screen.getByText(consent.text)).toBeTruthy();
    expect(document.querySelector("[data-profiling]")?.textContent).toBe("Off: only your niches and county are used.");
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(document.querySelector("[data-profiling]")?.getAttribute("data-profiling")).toBe("on"));
    expect(setImpl).toHaveBeenCalledWith(true, "v1");
    expect(screen.getByRole("button", { name: "Turn off" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("asks for a reload when the wording changed", async () => {
    const setImpl = vi.fn(async () => ({ ok: false as const, problem: "changed" as const }));
    renderWithIntl(<ProfilingToggle consent={consent} setImpl={setImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        "The wording of this consent has changed. Reload the page to read it, then decide again.",
      ),
    );
    expect(document.querySelector("[data-profiling]")?.getAttribute("data-profiling")).toBe("off");
  });
});
