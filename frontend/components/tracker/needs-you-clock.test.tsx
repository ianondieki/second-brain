import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import type { Summary } from "./model";
import { NeedsYouCard } from "./NeedsYouCard";

// P26 (REQ-TRACK-03): the Home "Needs you" / "Needs us" cards (the organisation's deadline rows) show the live clock
// while the stage's window is open, warm under 24 hours (the step is the viewer's on these cards); overdue, on hold
// and the organisation's answer-by case keep their words.

afterEach(cleanup);

const NOW = "2026-10-01T06:36:00.000Z";
const DUE = {
  due_on: "2026-10-07",
  business_days_left: 4,
  overdue: false,
  due_at: "2026-10-07T20:59:59.999Z",
} as Summary["due"];
const card = (over: Partial<Summary>, now?: string) =>
  renderWithIntl(
    <NeedsYouCard item={summary({ due: DUE, whose_turn: ["org"], ...over })} mine="org" href="/org/engagements/e" action="Open the tracker" now={now} />,
  );
const clock = () => document.querySelector<HTMLElement>("[data-deadline-clock]");

describe("the Needs-us card's deadline clock", () => {
  it("counts days, hours and minutes to due_at from the page's instant, the business days as its line, two chips", () => {
    card({}, NOW);
    expect(clock()?.querySelector("time")?.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect([...clock()!.querySelectorAll("[data-figure]")].map((figure) => figure.textContent)).toEqual(["6", "14", "23"]);
    expect(clock()?.querySelector("[data-due]")?.textContent).toBe("4 business days left, due 7 Oct 2026");
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(2);
    expect(document.querySelector("[aria-live]")).toBeNull();
  });

  it("is warm under 24 hours, the step being the organisation's", () => {
    card({}, "2026-10-07T08:00:00.000Z");
    expect(document.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("warm");
  });

  it("keeps the words when overdue, on the answer-by date, or without the page's instant", () => {
    card({ due: { ...DUE!, business_days_left: -1, overdue: true } }, NOW);
    expect(clock()).toBeNull();
    expect(document.querySelector("[data-due='overdue']")?.textContent).toBe("Overdue by 1 business day, was due 7 Oct 2026");
    cleanup();
    card({ state: "INFO_REQUESTED", whose_turn: ["developer", "org"] }, NOW);
    expect(clock()).toBeNull();
    expect(document.querySelector("[data-due]")?.textContent).toBe("Answer from Achieng Otieno due by 7 Oct 2026");
    cleanup();
    card({});
    expect(clock()).toBeNull();
    expect(document.querySelector("[data-due]")?.textContent).toBe("4 business days left, due 7 Oct 2026");
  });
});
