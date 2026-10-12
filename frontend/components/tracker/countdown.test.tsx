import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import type { Detail } from "./model";
import { WhoseTurn } from "./WhoseTurn";

// P23-3, P26 (REQ-TRACK-03): the tracker's deadline, for both parties, is the figure panel's live clock: the time left
// in days, hours and minutes to the end of the due day in Nairobi (the API's due_at), from the page's app-clock
// instant, the business-days sentence as its line; warm under 24 hours only when the viewer's party is awaited. Overdue
// keeps the error figure and its words; ended and on hold add nothing; without the API's instant the business-days
// figure stays; while a question is open the time left is a sentence under the question's clock line.

afterEach(cleanup);

const NOW = "2026-10-01T06:36:00.000Z";
const DUE = { due_on: "2026-10-07", business_days_left: 4, overdue: false, due_at: "2026-10-07T20:59:59.999Z" } as Detail["due"];

const panel = () => document.querySelector<HTMLElement>("[data-whose-turn] [data-clock-panel]");
const clock = () => document.querySelector<HTMLElement>("[data-whose-turn] [data-clock]");
const figures = () => [...(panel()?.querySelectorAll("[data-figure]") ?? [])].map((figure) => figure.textContent);
const timer = () => document.querySelector<HTMLElement>("[data-whose-turn] [data-timer]");

describe("the tracker's countdown", () => {
  it("is the figure panel's live clock, the business days its line: one deadline, said once and readable", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: DUE })} now={NOW} />);
    expect(panel()?.querySelector("[data-deadline-clock='lg']")).not.toBeNull();
    const time = panel()!.querySelector("time")!;
    expect(time.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(time.getAttribute("title")).toBe("7 Oct 2026, 23:59 EAT");
    expect(figures()).toEqual(["6", "14", "23"]);
    // The sentence is the clock's visible line, and not repeated for screen readers elsewhere in the banner.
    expect(panel()?.querySelector("[data-due]")?.textContent).toBe("4 business days left, due 7 Oct 2026");
    expect(document.querySelectorAll("[data-whose-turn] [data-due]")).toHaveLength(1);
    expect(document.querySelector("[data-whose-turn] .sr-only [data-due]")).toBeNull();
    expect(panel()?.closest("[aria-hidden='true']")).toBeNull();
    // Nothing hidden from screen readers but the clock's figures, whose words sit beside them.
    expect(panel()?.querySelector("[aria-hidden]:not([data-clock-figures])")).toBeNull();
    // The old business-days figure and the sentence countdown give way to it.
    expect(document.querySelector("[data-countdown]")).toBeNull();
    expect(timer()).toBeNull();
    expect(clock()?.getAttribute("data-clock")).toBe("open");
    expect(document.querySelector("[data-whose-turn] [aria-live]")).toBeNull();
  });

  it("is drawn for the organisation too, warm under 24 hours when the step is theirs", () => {
    renderWithIntl(
      <WhoseTurn detail={detail({ due: DUE, my_party: "org", my_roles: ["reviewer"], whose_turn: ["org"] })} now="2026-10-07T08:00:00.000Z" />,
    );
    expect(figures()).toEqual(["12", "59"]);
    expect(clock()?.getAttribute("data-clock")).toBe("warm");
  });

  it("stays neutral under 24 hours when the step is the other party's", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: DUE })} now="2026-10-07T08:00:00.000Z" />);
    expect(clock()?.getAttribute("data-clock")).toBe("open");
  });

  it("counts the last day too (due today), its line the sentence", () => {
    const today = { ...DUE, business_days_left: 0 } as Detail["due"];
    renderWithIntl(<WhoseTurn detail={detail({ due: today })} now="2026-10-07T15:00:00.000Z" />);
    expect(figures()).toEqual(["5", "59"]);
    expect(panel()?.querySelector("[data-due]")?.textContent).toBe("Due today, 7 Oct 2026");
    expect(panel()?.closest(".sr-only")).toBeNull();
  });

  it("keeps the error figure when overdue, the business-days figure without the API's instant, and adds nothing ended or on hold", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: { ...DUE, business_days_left: -2, overdue: true } as Detail["due"] })} now={NOW} />);
    expect(panel()).toBeNull();
    expect(document.querySelector("[data-countdown='overdue']")?.textContent).toBe("2 business days overdueWas due 7 Oct 2026");
    expect(document.querySelector("time[datetime^='P']")).toBeNull();
    cleanup();
    renderWithIntl(<WhoseTurn detail={detail({ due: { due_on: "2026-10-07", business_days_left: 4, overdue: false } })} now={NOW} />);
    expect(panel()).toBeNull();
    expect(document.querySelector("[data-countdown='open']")?.textContent).toBe("4 business days leftDue 7 Oct 2026");
    cleanup();
    const cases: Array<Partial<Detail>> = [
      { due: DUE, state: "DECLINED", whose_turn: [], awaiting: [], end_reason: "BUDGET" },
      { due: DUE, state: "ON_HOLD", whose_turn: [], awaiting: [], paused_from: "UNDER_REVIEW" },
    ];
    for (const over of cases) {
      renderWithIntl(<WhoseTurn detail={detail(over)} now={NOW} />);
      expect(panel(), JSON.stringify(over)).toBeNull();
      expect(timer(), JSON.stringify(over)).toBeNull();
      expect(document.querySelector("time[datetime^='P']"), JSON.stringify(over)).toBeNull();
      cleanup();
    }
  });

  it("draws the developer's answer-by date as their clock while a question is open; the organisation reads a sentence", () => {
    const question = { due: DUE, state: "INFO_REQUESTED" as const, whose_turn: ["developer" as const], paused_from: "UNDER_REVIEW" as const };
    // The developer's own deadline: the clock, as on their cards.
    renderWithIntl(<WhoseTurn detail={detail({ ...question, my_party: "developer" })} now={NOW} />);
    expect(panel()).not.toBeNull();
    expect(panel()?.querySelector("time")?.getAttribute("datetime")).toBe("P6DT14H23M");
    // The date is said once, in the question's sentence: the panel draws the clock without a words line.
    expect(panel()?.querySelector("[data-deadline-clock] p")).toBeNull();
    expect(document.querySelector("[data-due]")).toBeNull();
    cleanup();
    // The organisation waits on the answer: no clock of its own, the time left in the question's sentence.
    renderWithIntl(<WhoseTurn detail={detail({ ...question, my_party: "org" })} now={NOW} />);
    expect(panel()).toBeNull();
    expect(timer()?.textContent).toBe("in 6 days 14 h 23 min");
    expect(timer()?.getAttribute("data-timer")).toBe("open");
  });

  it("gives the clock panel the clock's own width from 640 px, never narrower than 16 rem (two-digit days, Swahili)", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: DUE })} now={NOW} />);
    expect(panel()?.className).toContain("sm:w-min");
    expect(panel()?.className).toContain("sm:min-w-64");
    expect(panel()?.className).not.toMatch(/\bsm:w-60\b/);
  });
});
