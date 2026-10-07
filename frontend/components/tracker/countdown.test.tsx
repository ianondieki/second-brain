import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import type { Detail } from "./model";
import { WhoseTurn } from "./WhoseTurn";

// P23-3 (REQ-TRACK-03): the tracker's deadline, for both parties, gains the time left in days, hours and minutes to
// the end of the due day in Nairobi (the API's due_at), from the page's app-clock instant; warm under 24 hours only
// when the viewer's party is awaited; nothing new once overdue, ended or on hold, or when the API sends no instant.

afterEach(cleanup);

const NOW = "2026-10-01T06:36:00.000Z";
const DUE = { due_on: "2026-10-07", business_days_left: 4, overdue: false, due_at: "2026-10-07T20:59:59.999Z" } as Detail["due"];

const timer = () => document.querySelector<HTMLElement>("[data-whose-turn] [data-timer]");

describe("the tracker's countdown", () => {
  it("is the figure's one secondary line, with the date: one deadline, said once (the figure stays a picture of the sentence)", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: DUE })} now={NOW} />);
    expect(timer()?.textContent).toBe("Due 7 Oct 2026 · in 6 days 14 h 23 min");
    expect(document.querySelector("[data-countdown='open']")?.textContent).toBe("4 business days left"); // no second date
    expect(timer()?.closest("[aria-hidden='true']")).toBeNull();
    expect(timer()?.parentElement?.querySelector("[data-countdown='open']")).not.toBeNull();
    expect(timer()?.getAttribute("data-timer")).toBe("open");
  });

  it("is said for the organisation too, warm under 24 hours when the step is theirs", () => {
    renderWithIntl(
      <WhoseTurn detail={detail({ due: DUE, my_party: "org", my_roles: ["reviewer"], whose_turn: ["org"] })} now="2026-10-07T08:00:00.000Z" />,
    );
    expect(timer()?.textContent).toBe("Due 7 Oct 2026 · in 12 h 59 min");
    expect(timer()?.getAttribute("data-timer")).toBe("warm");
  });

  it("stays neutral under 24 hours when the step is the other party's", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: DUE })} now="2026-10-07T08:00:00.000Z" />);
    expect(timer()?.getAttribute("data-timer")).toBe("open");
  });

  it("follows the sentence when there is no figure (due today)", () => {
    const today = { ...DUE, business_days_left: 0 } as Detail["due"];
    renderWithIntl(<WhoseTurn detail={detail({ due: today })} now="2026-10-07T15:00:00.000Z" />);
    expect(document.querySelector("[data-countdown]")).toBeNull();
    expect(timer()?.textContent).toBe("in 5 h 59 min");
    expect(timer()?.closest(".sr-only")).toBeNull();
  });

  it("adds nothing when overdue, ended, on hold, or without the API's instant", () => {
    const cases: Array<Partial<Detail>> = [
      { due: { ...DUE, business_days_left: -2, overdue: true } as Detail["due"] },
      { due: DUE, state: "DECLINED", whose_turn: [], awaiting: [], end_reason: "BUDGET" },
      { due: DUE, state: "ON_HOLD", whose_turn: [], awaiting: [], paused_from: "UNDER_REVIEW" },
      { due: { due_on: "2026-10-07", business_days_left: 4, overdue: false } },
    ];
    for (const over of cases) {
      renderWithIntl(<WhoseTurn detail={detail(over)} now={NOW} />);
      expect(timer(), JSON.stringify(over)).toBeNull();
      cleanup();
    }
  });
});
