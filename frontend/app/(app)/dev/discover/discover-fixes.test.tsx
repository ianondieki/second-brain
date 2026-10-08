import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import sw from "@/locales/sw.json";
import { renderWithIntl } from "@/test/intl";
import { recommendation, recommendations, trendingProblem, trendingProject } from "@/test/discover";

import { DiscoverList } from "./DiscoverList";
import { NichePicker } from "./niches/NichePicker";
import { ProfilingToggle } from "./niches/ProfilingToggle";
import { ProblemRow } from "./ProblemRow";
import { ProjectRow } from "./ProjectRow";
import { RecommendedForYou } from "./RecommendedForYou";
import { recommendationsState } from "./recommendations";

// P12-F fix round (REQ-TREND-02, REQ-PERS-01, REQ-PERS-03): provenance on every card, projects cold start, no
// "Trending" for what does not trend, the unavailable Home state, literal text for API words, https-only source
// links, the Swahili pursuit chip, and the picker's and the consent's edge cases.

afterEach(cleanup);

const COUNTIES = [{ code: "KE-30", name: "Nairobi City" }];
const MARKUP = '<img src=x onerror="alert(1)"><b>bold</b>';
const QUIET = { trending: false, new_this_week: true, z: 1.3, score: 3, badge: null };

function renderSw(ui: ReactElement) {
  return render(
    <NextIntlClientProvider locale="sw" messages={sw}>
      {ui}
    </NextIntlClientProvider>,
  );
}

describe("provenance", () => {
  it("shows the problem's label on a Discover card and on a Home recommendation, as the problem page words it", () => {
    const seeded = "Seeded example for the demo (not a live AI result), human-reviewed on 30 September 2026";
    const { unmount } = renderWithIntl(
      <ProblemRow item={trendingProblem()} counties={COUNTIES} query={{ view: "problems" }} />,
    );
    expect(document.querySelector("[data-label]")?.textContent).toBe("Developer-reported");
    unmount();
    // The API's English label says "30 September 2026"; the page builds its own, in the problem page's date format.
    const item = recommendation({ problem: { ...recommendation().problem, label: seeded, seeded_example: true } });
    const home = renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations({ items: [item] }))} />);
    // A seeded example shows the small "Demo data" badge with the full sentence behind it (D-52).
    expect(document.querySelector("[data-label]")?.textContent).toBe(
      "Demo dataSeeded example for the demo (not a live AI result), human-reviewed on 30 Sep 2026",
    );
    home.unmount();
    // An API without the field: its own words, never a guess.
    const { seeded_example: _dropped, ...older } = item.problem;
    void _dropped;
    renderWithIntl(
      <RecommendedForYou state={recommendationsState(recommendations({ items: [{ ...item, problem: older as typeof item.problem }] }))} />,
    );
    expect(document.querySelector("[data-label]")?.textContent).toBe(seeded);
  });

  it("labels the problem a project solves (P12-F re-review MINOR 5)", () => {
    const project = trendingProject({
      problem: { ...trendingProject().problem, source: "research_agent", label: "x", seeded_example: false },
    });
    renderWithIntl(<ProjectRow item={project} />);
    const solves = document.querySelector("[data-solves]")!;
    expect(solves.querySelector("[data-label]")?.textContent).toBe("AI-drafted, human-reviewed on 30 Sep 2026");
  });

  it("words the missing sources by who described the problem", () => {
    for (const [source, sentence] of [
      ["developer", "No cited sources: a developer described this problem."],
      ["org_brief", "No cited sources: a verified organisation described this problem in its Brief."],
      ["research_agent", "No source to show here; the problem card lists every source it cites."],
    ] as const) {
      const item = trendingProblem({ sources: [], problem: { ...trendingProblem().problem, source } });
      const { unmount } = renderWithIntl(<ProblemRow item={item} counties={COUNTIES} query={{ view: "problems" }} />);
      expect(screen.getByText(sentence)).toBeTruthy();
      unmount();
    }
  });
});

describe("honest trends", () => {
  it("drops a Trending chip from a problem that does not trend", () => {
    const item = trendingProblem({ trend: QUIET, why: ["Trending in its niche", "2 new sources this month", "New this week"] });
    renderWithIntl(<ProblemRow item={item} counties={COUNTIES} query={{ view: "problems" }} />);
    const card = screen.getByRole("article");
    expect([...card.querySelectorAll("[data-chip]")].map((chip) => chip.textContent)).toEqual([
      "2 new sources this month",
      "New this week",
    ]);
    expect(card.textContent).not.toContain("Trending");
  });

  it("drops a Trending reason and chip from a recommendation that does not trend, and never repeats a reason", () => {
    const item = recommendation({
      trend: QUIET,
      why: ["Trending in its niche", "In a niche you like", "Good fit for you"],
      pursuit: { decision: "consider", label: "Consider", reasons: ["Trending in its niche", "Good fit for you"] },
    });
    renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations({ items: [item] }))} />);
    const card = screen.getByRole("article");
    expect(card.textContent).not.toContain("Trending");
    expect(card.querySelector("[data-chip=why]")?.textContent).toBe("In a niche you like");
    const reasons = within(card).getByRole("heading", { name: "Why “Consider”" }).closest("section")!;
    expect(within(reasons).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Good fit for you"]);
    const fits = within(card).getByRole("heading", { name: "Why it fits" }).closest("section")!;
    expect(within(fits).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["In a niche you like"]);
  });

  it("titles a projects list with nothing trending as new this week", () => {
    const quiet = trendingProject({ trend: { trending: false, new_this_week: true, badge: null } });
    const board = { generated_at: "2026-09-30T06:42:45+03:00", problems: [], projects: [quiet] };
    const { unmount } = renderWithIntl(<DiscoverList kind="board" board={board} query={{ view: "projects" }} counties={COUNTIES} />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("New this week");
    expect(screen.getByText("Nothing is trending here yet, so these are the projects published in the last 7 days.")).toBeTruthy();
    unmount();
    renderWithIntl(
      <DiscoverList kind="board" board={{ ...board, projects: [trendingProject(), quiet] }} query={{ view: "projects" }} counties={COUNTIES} />,
    );
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Trending projects");
    expect(screen.getByText("Rising fastest first, then new this week; each one beside the problem it solves.")).toBeTruthy();
  });
});

describe("Home when recommendations cannot be shown", () => {
  it("is one sentence and one action to Discover", () => {
    renderWithIntl(<RecommendedForYou state={recommendationsState(null)} />);
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(within(empty).getByText("Recommendations cannot be shown right now.")).toBeTruthy();
    expect(within(empty).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Open Discover", "/dev/discover"],
    ]);
    expect(document.querySelector("article")).toBeNull();
  });
});

describe("the API's words are text", () => {
  it("renders markup in a chip, a badge, a source and a Why-not line literally", () => {
    const item = trendingProblem({
      why: [MARKUP, "New this week"],
      trend: { ...trendingProblem().trend, badge: "Trending in <i>ICT</i> · Kenya: 4 companies scouting" },
      sources: [{ ...trendingProblem().sources[0], publisher: MARKUP, quote: MARKUP }],
    });
    const { unmount } = renderWithIntl(<ProblemRow item={item} counties={COUNTIES} query={{ view: "problems" }} />);
    // No element from the API's words (the card's own niche photograph band, P25, is the only image).
    expect([...document.querySelectorAll("img")].filter((img) => !img.closest("[data-niche-band]"))).toHaveLength(0);
    expect(document.querySelector("b")).toBeNull();
    // The card shows the badge's short form (its title keeps the sentence); the markup stays text either way.
    expect(document.querySelector("[data-badge]")?.textContent).toBe("Trending: 4 companies scouting");
    expect(document.querySelector("[data-badge]")?.getAttribute("title")).toBe("Trending in <i>ICT</i> · Kenya: 4 companies scouting");
    expect(document.querySelector("i")).toBeNull();
    expect(document.querySelector("[data-chip]")?.textContent).toBe(MARKUP);
    unmount();
    const rec = recommendation({ why: [MARKUP], why_not: MARKUP });
    renderWithIntl(<RecommendedForYou state={recommendationsState(recommendations({ items: [rec] }))} />);
    // No element from the API's words (the card's own niche photograph band, P25, is the only image).
    expect([...document.querySelectorAll("img")].filter((img) => !img.closest("[data-niche-band]"))).toHaveLength(0);
    expect(document.querySelector("[data-chip=why]")?.textContent).toBe(MARKUP);
    expect(screen.getAllByText(MARKUP).length).toBeGreaterThanOrEqual(2);
  });

  it("links a source only when it is a plain https address", () => {
    for (const url of ["javascript:alert(1)", "https://user:pw@example.com/report", "http://example.com/report", "data:text/html,x"]) {
      const item = trendingProblem({ sources: [{ ...trendingProblem().sources[0], url, publisher: "Kenya Gazette" }] });
      const { unmount } = renderWithIntl(<ProblemRow item={item} counties={COUNTIES} query={{ view: "problems" }} />);
      expect(screen.getByText("Kenya Gazette").closest("a"), url).toBeNull();
      unmount();
    }
  });
});

describe("in Swahili", () => {
  it("words the pursuit chip from our own keys", () => {
    const items = [
      recommendation(),
      recommendation({ position: 2, problem: { ...recommendation().problem, id: "b" }, label: "Stretch", pursuit: { decision: "not_now", label: "Not now", reasons: ["x"] } }),
    ];
    renderSw(<RecommendedForYou state={recommendationsState(recommendations({ items }))} />);
    expect([...document.querySelectorAll("[data-chip=pursuit]")].map((chip) => chip.textContent)).toEqual([
      "Fuatilia · Inafaa",
      "Si sasa · Changamoto",
    ]);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Yanayopendekezwa kwako");
  });
});

describe("the picker and the consent", () => {
  it("focuses the count error when more than five are chosen", async () => {
    const saveImpl = vi.fn();
    renderWithIntl(
      <NichePicker
        niches={["a", "b", "c", "d", "e", "f"].map((id) => ({ id, name: `Niche ${id}`, children: [] }))}
        initial={["a", "b", "c", "d", "e"]}
        min={3}
        max={5}
        saveImpl={saveImpl}
      />,
    );
    fireEvent.click(screen.getByLabelText("Niche f"));
    fireEvent.click(screen.getByRole("button", { name: "Save niches" }));
    const error = screen.getByRole("alert");
    expect(error.textContent).toBe("Choose at most 5 niches.");
    await waitFor(() => expect(document.activeElement).toBe(error));
    expect(saveImpl).not.toHaveBeenCalled();
  });

  it("shows what the API recorded, not what was asked, and describes its button by the title", async () => {
    const consent = { granted: false, text: "Use my niches and activity to recommend problems.", version: "v1" };
    const setImpl = vi.fn(async () => ({
      ok: true as const,
      value: { purpose: "profiling" as const, granted: false, text: consent.text, version: "v1" },
    }));
    renderWithIntl(<ProfilingToggle consent={consent} setImpl={setImpl} />);
    const button = screen.getByRole("button", { name: "Turn on" });
    expect(button.getAttribute("aria-describedby")).toBe("profiling-title");
    expect(document.getElementById("profiling-title")?.textContent).toBe("Use your activity");
    fireEvent.click(button);
    await waitFor(() => expect(setImpl).toHaveBeenCalledWith(true, "v1"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Turn on" }).getAttribute("aria-disabled")).toBeNull());
    expect(document.querySelector("[data-profiling]")?.getAttribute("data-profiling")).toBe("off");
  });
});
