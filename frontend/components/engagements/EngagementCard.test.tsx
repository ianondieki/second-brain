import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Summary } from "@/components/tracker/model";
import { summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { EngagementCard } from "./EngagementCard";

afterEach(cleanup);

// P25 (D-67; REQ-UX-02): an engagement as a card for both sides' lists: the title as the one link, five dots for where
// it stands (one image with its words), at most two chips, who it waits on, the countdown.
describe("EngagementCard", () => {
  it("links its title, reads its stage as one image and keeps to two chips when it is your turn", () => {
    renderWithIntl(
      <EngagementCard
        item={summary({
          state: "NEGOTIATION",
          stage_group: "agreement",
          stage_label: "Terms drafting",
          whose_turn: ["developer"],
        })}
        mine="developer"
        href="/dev/engagements/e1"
      />,
    );
    const card = screen.getByRole("article");
    expect(within(card).getAllByRole("link")).toHaveLength(1);
    expect(within(card).getByRole("img", { name: "Stage 3 of 5: Terms drafting" })).toBeTruthy();
    expect(card.querySelectorAll("[data-dot]")).toHaveLength(5);
    expect([...card.querySelectorAll("[data-dot]")].map((d) => d.getAttribute("data-dot"))).toEqual([
      "completed",
      "completed",
      "current",
      "pending",
      "pending",
    ]);
    expect(card.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    expect(within(card).getByText("Your turn")).toBeTruthy();
    expect(card.getAttribute("data-turn")).toBe("mine");
  });

  it("says who it waits on otherwise, titled by the organisation under an idea", () => {
    renderWithIntl(
      <EngagementCard
        item={summary({ state: "NEGOTIATION", stage_group: "agreement", whose_turn: ["org"], org_name: "SACCO B" })}
        mine="developer"
        titleBy="organisation"
        href="/dev/engagements/e1"
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "SACCO B" })).toBeTruthy();
    expect(screen.getByText("Waiting on SACCO B")).toBeTruthy();
    expect(screen.queryByText("Your turn")).toBeNull();
  });

  it("never sets a named organisation's premises over an organisation's name; titled by the idea, the niche's photograph", () => {
    const item = summary({
      state: "NEGOTIATION",
      stage_group: "agreement",
      whose_turn: ["org"],
      org_name: "Kenyatta University",
    });
    const band = () => document.querySelector("[data-niche-band]")?.getAttribute("data-niche-band");
    // Education's photograph is Strathmore's campus: over another university's name it would read as theirs.
    renderWithIntl(
      <EngagementCard
        item={item}
        mine="developer"
        titleBy="organisation"
        niche={{ slug: "higher-education" }}
        href="/dev/engagements/e1"
      />,
    );
    expect(band()).toBe("lattice");
    cleanup();
    renderWithIntl(
      <EngagementCard item={item} mine="developer" niche={{ slug: "higher-education" }} href="/dev/engagements/e1" />,
    );
    expect(band()).toBe("nairobi-strathmore-campus");
  });
});

// P26 (REQ-TRACK-03): every active engagement's card shows the live clock to the stage's `due_at` (days, hours,
// minutes from the page's app-clock instant), the business days as its line; overdue, on hold, ended and the
// organisation's answer-by case keep their words; warm under 24 hours only when the step is the viewer's.
describe("EngagementCard's deadline clock", () => {
  const NOW = "2026-10-01T06:36:00.000Z";
  const DUE = {
    due_on: "2026-10-07",
    business_days_left: 4,
    overdue: false,
    due_at: "2026-10-07T20:59:59.999Z",
  } as Summary["due"];
  const card = (over: Partial<Summary>, mine: "developer" | "org" = "developer", now: string | null = NOW) =>
    renderWithIntl(
      <EngagementCard
        item={summary({ due: DUE, ...over })}
        mine={mine}
        href="/dev/engagements/e1"
        now={now ?? undefined}
      />,
    );
  const clock = () => document.querySelector<HTMLElement>("[data-deadline-clock]");

  it("draws the clock from a fixed now and due_at: a <time> with the duration and three figures, the business days as its line", () => {
    card({});
    const time = clock()!.querySelector("time")!;
    expect(time.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(time.getAttribute("title")).toBe("7 Oct 2026, 23:59 EAT");
    expect([...clock()!.querySelectorAll("[data-figure]")].map((figure) => figure.textContent)).toEqual([
      "6",
      "14",
      "23",
    ]);
    expect(clock()!.querySelector("[data-due]")?.textContent).toBe("4 business days left, due 7 Oct 2026");
    // The clock's line is the deadline's one sentence: not said twice.
    expect(document.querySelectorAll("[data-due]")).toHaveLength(1);
    expect(document.querySelector("[aria-live]")).toBeNull();
    expect(document.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
  });

  it("is drawn for the organisation's cards too", () => {
    card({ whose_turn: ["developer"] }, "org");
    expect(clock()?.querySelector("time")?.getAttribute("dateTime")).toBe("P6DT14H23M");
  });

  it("keeps the words when overdue, on hold, ended, the organisation's answer-by, or without the page's instant", () => {
    const cases: Array<[Partial<Summary>, "developer" | "org", string | null, string | null]> = [
      [
        { due: { ...DUE!, business_days_left: -2, overdue: true } },
        "developer",
        NOW,
        "Overdue by 2 business days, was due 7 Oct 2026",
      ],
      [{ state: "ON_HOLD", whose_turn: [], paused_from: "UNDER_REVIEW" }, "developer", NOW, "Resumes 7 Oct 2026"],
      [{ state: "CLOSED", whose_turn: [] }, "developer", NOW, null],
      [{ state: "DECLINED", whose_turn: [], end_reason: "BUDGET" }, "org", NOW, null],
      [
        { state: "INFO_REQUESTED", whose_turn: ["developer"] },
        "org",
        NOW,
        "Answer from Achieng Otieno due by 7 Oct 2026",
      ],
      [{}, "developer", null, "4 business days left, due 7 Oct 2026"],
      [
        { due: { due_on: "2026-10-07", business_days_left: 4, overdue: false } },
        "developer",
        NOW,
        "4 business days left, due 7 Oct 2026",
      ],
    ];
    for (const [over, mine, now, words] of cases) {
      card(over, mine, now);
      expect(clock(), JSON.stringify(over)).toBeNull();
      expect(document.querySelector("time[datetime^='P']"), JSON.stringify(over)).toBeNull();
      expect(document.querySelector("[data-due]")?.textContent ?? null, JSON.stringify(over)).toBe(words);
      cleanup();
    }
  });

  it("is the developer's answer-by clock while a question waits on them", () => {
    card({ state: "INFO_REQUESTED", whose_turn: ["developer"] }, "developer");
    expect(clock()).not.toBeNull();
  });

  it("is warm under 24 hours only on the viewer's step", () => {
    const soon = "2026-10-07T08:00:00.000Z";
    card({ whose_turn: ["developer"] }, "developer", soon);
    expect(document.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("warm");
    cleanup();
    card({ whose_turn: ["org"] }, "developer", soon);
    expect(document.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("open");
    cleanup();
    card({ whose_turn: ["developer"] }, "developer");
    expect(document.querySelector("[data-clock]")?.getAttribute("data-clock")).toBe("open");
  });

  it("fetches its band at once only when told it is the list's first card (the page's LCP)", () => {
    const item = summary({ state: "NEGOTIATION", stage_group: "agreement", whose_turn: ["org"] });
    const img = () => document.querySelector("[data-niche-band] img");
    renderWithIntl(
      <EngagementCard item={item} mine="developer" niche={{ slug: "agriculture" }} href="/dev/engagements/e1" eager />,
    );
    expect(img()?.getAttribute("loading")).toBe("eager");
    expect(img()?.getAttribute("fetchpriority")).toBe("high");
    cleanup();
    renderWithIntl(
      <EngagementCard item={item} mine="developer" niche={{ slug: "agriculture" }} href="/dev/engagements/e1" />,
    );
    expect(img()?.getAttribute("loading")).toBe("lazy");
  });
});
