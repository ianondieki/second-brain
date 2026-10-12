import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { pipeline, pipelineItem } from "@/test/deadlines";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { Board } from "./Board";
import { assignedTo, hasTeamFacts, type Pipeline } from "./data";
import { conversion } from "./Funnel";

// P27 track B (REQ-ENG-14): the organisation's Board, server-rendered. The funnel strip of the last 90 days (figures
// as text, bars in the tokens, conversions between neighbours with a sentence read out), the five stage columns with
// count and median days, compact cards with at most two chips (Our turn, the stalled mark; no stage chip), the
// assignee as a quiet line, "Assigned to me", a row that scrolls inside itself on a phone; an empty board: one
// sentence and one action.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
afterEach(cleanup);

const ID = (n: number) => `0193f0c8-6a8f-7b4c-9d2e-3f4a5b6c7d${String(n).padStart(2, "0")}`;

async function board(value: Pipeline, filter?: { on: boolean; allHref: string; mineHref: string }) {
  const tree = await Board({
    pipeline: value,
    cardHref: (id) => `/org/engagements/${id}`,
    filter,
    emptyHref: "/org/inbox/scouts/new",
  });
  return renderWithIntl(<>{await resolveServerTree(tree)}</>).container;
}

describe("the columns", () => {
  it("are the five stage groups in order, each with its name, count and median days in stage", async () => {
    const value = pipeline(
      {
        review: [pipelineItem({ id: ID(1) }), pipelineItem({ id: ID(2) })],
        agreement: [pipelineItem({ id: ID(3), state: "AGREEMENT_SIGNING", whose_turn: ["developer"] })],
      },
      { review: 4, contact_nda: 2 },
    );
    value.columns[0].median_days_in_stage = 3.4;
    const container = await board(value);
    const columns = [...container.querySelectorAll<HTMLElement>("[data-column]")];
    expect(columns.map((column) => column.getAttribute("data-column"))).toEqual([
      "review",
      "contact_nda",
      "agreement",
      "implementation",
      "close",
    ]);
    expect(columns.map((column) => column.querySelector("h3")?.textContent)).toEqual([
      "Review",
      "Contact and NDA",
      "Agreement",
      "Implementation",
      "Close",
    ]);
    expect(columns[0].querySelector("[data-count]")?.textContent).toBe("2 engagements");
    expect(columns[0].querySelector("[data-median]")?.textContent).toBe("median 3 days in stage");
    expect(columns[1].querySelector("[data-median]")).toBeNull();
    expect(columns[1].textContent).toContain("None at this stage.");
    expect(columns[2].querySelectorAll("[data-engagement]")).toHaveLength(1);
  });

  it("scroll sideways inside their own focusable region on a phone, five equal columns from 1024 px", async () => {
    const container = await board(pipeline({ review: [pipelineItem()] }, { review: 1 }));
    const row = container.querySelector<HTMLElement>("[data-board-row]")!;
    expect(row.getAttribute("role")).toBe("region");
    expect(row.getAttribute("tabindex")).toBe("0");
    expect(row.className).toContain("overflow-x-auto");
    expect(row.className).toContain("snap-x");
    expect(row.querySelector("ol")?.className).toContain("lg:grid-cols-5");
    expect(container.querySelector("[data-column]")?.className).toContain("w-[85vw]");
  });
});

describe("a card", () => {
  it("says the developer, links the idea's title once, the clock, and at most two chips: Our turn and stalled", async () => {
    const container = await board(
      pipeline({ review: [pipelineItem({ id: ID(1), stalled: true, whose_turn: ["org"] })] }, { review: 1 }),
    );
    const card = container.querySelector<HTMLElement>(`[data-engagement="${ID(1)}"]`)!;
    expect(within(card).getAllByRole("link")).toHaveLength(1);
    expect(within(card).getByRole("link").getAttribute("href")).toBe(`/org/engagements/${ID(1)}`);
    expect(card.querySelector("[data-avatar='person']")).not.toBeNull();
    expect(card.querySelector("[data-clock]")).not.toBeNull();
    const chips = [...card.querySelectorAll("[data-chip]")].map((chip) => chip.getAttribute("data-chip"));
    expect(chips).toEqual(["turn", "stalled"]);
    expect(card.querySelector("[data-chip='stalled']")?.textContent).toBe("No movement for 5 business days");
    expect(card.querySelector("[data-chip='turn']")?.textContent).toBe("Our turn");
  });

  it("drops the stage chip (the column says it) and carries no chip when it is neither ours nor stalled", async () => {
    const container = await board(pipeline({ review: [pipelineItem({ id: ID(1), whose_turn: ["developer"] })] }, { review: 1 }));
    const card = container.querySelector<HTMLElement>(`[data-engagement="${ID(1)}"]`)!;
    expect(card.querySelectorAll("[data-chip]")).toHaveLength(0);
  });

  it("names the assignee in a quiet line, not a chip", async () => {
    const team = { assignee: { user_id: "u-2", display_name: "Wanjiru Kamau" }, recommendations: { pursue: 1, pass: 0, discuss: 0 }, mine: null };
    const container = await board(pipeline({ review: [pipelineItem({ id: ID(1), team })] }, { review: 1 }));
    const line = container.querySelector<HTMLElement>("[data-assignee='u-2']")!;
    expect(line.textContent).toBe("Assigned to Wanjiru Kamau");
    expect(line.closest("[data-chip]")).toBeNull();
  });
});

describe("the funnel", () => {
  it("shows what entered each group in the window as figures, bars scaled to the largest, and the conversions", async () => {
    const container = await board(
      pipeline({ review: [pipelineItem()] }, { review: 12, contact_nda: 8, agreement: 4, implementation: 0, close: 0 }),
    );
    expect(screen.getByRole("heading", { level: 2, name: "Entered in the last 90 days" })).toBeTruthy();
    const groups = [...container.querySelectorAll<HTMLElement>("[data-funnel-group]")];
    expect(groups.map((g) => g.querySelector("[data-entered]")?.textContent)).toEqual(["12", "8", "4", "0", "0"]);
    expect(groups.map((g) => g.querySelector("[data-bar]")?.getAttribute("width"))).toEqual(["100", String((8 / 12) * 100), String((4 / 12) * 100), "0", "0"]);
    // Between neighbours: the share that went on, a picture of the sentence read out; none after a group with none.
    expect(groups[0].querySelector("[data-conversion]")).toBeNull();
    expect(groups[1].querySelector("[data-conversion] [aria-hidden='true']")?.textContent).toBe("67%");
    expect(groups[1].querySelector(".sr-only")?.textContent).toBe("8 of 12 went on to Contact and NDA");
    expect(groups[3].querySelector("[data-conversion] [aria-hidden='true']")?.textContent).toBe("0%");
    expect(groups[4].querySelector("[data-conversion]")?.textContent).toBe("");
    expect(container.querySelector("[data-funnel-outcome]")?.textContent).toBe("1 closed and 2 ended in the same window.");
    expect(container.querySelector("svg [data-bar]")?.getAttribute("class")).toContain("fill-(--heat-3)");
  });

  it("rounds the conversion and has none from a group nothing entered", () => {
    expect(conversion(12, 8)).toBe(67);
    expect(conversion(3, 3)).toBe(100);
    expect(conversion(0, 0)).toBeNull();
  });
});

describe("Assigned to me", () => {
  const mine = { assignee: { user_id: "me", display_name: "Me" }, recommendations: { pursue: 0, pass: 0, discuss: 0 }, mine: null };
  const theirs = { ...mine, assignee: { user_id: "them", display_name: "Them" } };

  it("keeps only the person's cards, the counts and medians theirs; offered only with the triage facts", () => {
    const value = pipeline({
      review: [pipelineItem({ id: ID(1), team: mine, days_in_stage: 2 }), pipelineItem({ id: ID(2), team: theirs })],
      close: [pipelineItem({ id: ID(3), team: null })],
    });
    expect(hasTeamFacts(value)).toBe(true);
    expect(hasTeamFacts(pipeline({ review: [pipelineItem()] }))).toBe(false);
    const filtered = assignedTo(value, "me");
    expect(filtered.columns[0].items.map((item) => item.id)).toEqual([ID(1)]);
    expect(filtered.columns[0].count).toBe(1);
    expect(filtered.columns[0].median_days_in_stage).toBe(2);
    expect(filtered.columns[4]).toMatchObject({ count: 0, median_days_in_stage: null });
    expect(filtered.funnel).toEqual(value.funnel);
  });

  it("is a pair of links, the current one marked; nothing assigned: one sentence and the way back to all", async () => {
    const filter = { on: false, allHref: "/org/engagements?view=board", mineHref: "/org/engagements?view=board&assignee=me" };
    await board(pipeline({ review: [pipelineItem({ team: mine })] }, { review: 1 }), filter);
    const nav = screen.getByRole("navigation", { name: "Whose engagements" });
    expect(within(nav).getByRole("link", { name: "All" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Assigned to me" }).getAttribute("href")).toBe(filter.mineHref);
    cleanup();
    const container = await board(pipeline({}, { review: 1 }), { ...filter, on: true });
    const empty = container.querySelector<HTMLElement>("[data-board='mine-empty']")!;
    expect(empty.textContent).toContain("Nothing is assigned to you.");
    expect(within(empty).getByRole("link", { name: "Show all engagements" }).getAttribute("href")).toBe(filter.allHref);
  });
});

describe("an empty board", () => {
  it("is one sentence and one action: set up a scout", async () => {
    const container = await board(pipeline());
    const empty = container.querySelector<HTMLElement>("[data-board='empty']")!;
    expect(empty.textContent).toContain("No engagements to show on the board yet.");
    expect(within(empty).getAllByRole("link")).toHaveLength(1);
    expect(within(empty).getByRole("link", { name: "Set up a scout" }).getAttribute("href")).toBe("/org/inbox/scouts/new");
    expect(container.querySelector("[data-funnel]")).toBeNull();
  });
});
