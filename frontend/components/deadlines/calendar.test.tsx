import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { deadline } from "@/test/deadlines";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Deadline } from "./month";

// P27 track A (REQ-ENG-13): the Calendar tab, server-rendered. The month as weeks (Monday first, Nairobi days), today
// marked, at most two chips a day then "+n more" (a link to the day's list), overdue in the error tone, the viewer's
// own turn in the warm one; the list under it, the live clock on the next thing due only, each row's Add to calendar
// (.ics and Google Calendar); nothing due at all: one sentence and one action.

const state = vi.hoisted(() => ({
  now: "2026-10-12T06:36:00.000Z",
  grid: [] as unknown[],
  list: [] as unknown[],
  refusal: null as null | "mfaSetup" | "notFound",
  reads: [] as Array<{ span: unknown; orgId?: string }>,
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/api/server", () => ({ appNow: () => state.now }));
vi.mock("./data", async (original) => ({
  ...(await original<typeof import("./data")>()),
  readDeadlines: async (span: { from?: string; to: string }, orgId?: string) => {
    state.reads.push({ span, orgId });
    if (state.refusal) return { ok: false, refusal: state.refusal };
    return { ok: true, value: { items: span.from ? state.grid : state.list, now: state.now } };
  },
}));

const { MonthCalendar } = await import("./MonthCalendar");
const { DeadlineList } = await import("./DeadlineList");
const { CalendarView } = await import("./CalendarView");

beforeEach(() => {
  state.grid = [];
  state.list = [];
  state.refusal = null;
  state.reads = [];
});
afterEach(cleanup);

const href = ({ month, day }: { month: string; day?: string }) =>
  `/dev/engagements?view=calendar&month=${month}${day ? `&day=${day}#day-list` : ""}`;

async function month(items: Deadline[], today = "2026-10-12") {
  return renderWithIntl(
    <>{await resolveServerTree(<MonthCalendar month="2026-10" today={today} items={items} href={href} />)}</>,
  ).container;
}

const cell = (container: HTMLElement, day: string) => container.querySelector<HTMLElement>(`td[data-day="${day}"]`)!;

describe("the month", () => {
  it("is a table of weeks, Monday first, its name the heading, today ringed and marked as the current date", async () => {
    const container = await month([]);
    expect(screen.getByRole("heading", { level: 2, name: "October 2026" })).toBeTruthy();
    const table = screen.getByRole("table", { name: "October 2026" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((th) => th.querySelector("abbr")?.getAttribute("title")),
    ).toEqual(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]);
    expect(table.querySelectorAll("tbody tr")).toHaveLength(5);
    expect(cell(container, "2026-09-28").hasAttribute("data-out")).toBe(true);
    expect(cell(container, "2026-10-01").hasAttribute("data-out")).toBe(false);
    const today = cell(container, "2026-10-12").querySelector("[aria-current='date']")!;
    expect(today.textContent).toBe("12");
    expect(today.className).toContain("ring-accent");
    expect(container.querySelectorAll("[aria-current='date']")).toHaveLength(1);
  });

  it("links to the months either side, each named in full", async () => {
    await month([]);
    expect(screen.getByRole("link", { name: "Previous month, September 2026" }).getAttribute("href")).toBe(
      "/dev/engagements?view=calendar&month=2026-09",
    );
    expect(screen.getByRole("link", { name: "Next month, November 2026" }).getAttribute("href")).toBe(
      "/dev/engagements?view=calendar&month=2026-11",
    );
  });

  it("shows at most two chips a day, then +n more linking to the day's list; the day itself is that link too", async () => {
    const day = "2026-10-16";
    const items = ["a", "b", "c", "d"].map((id) => deadline({ key: `stage:${id}`, title: `Idea ${id}`, due_on: day }));
    const container = await month(items);
    const td = cell(container, day);
    expect(td.querySelectorAll("[data-chip-deadline]")).toHaveLength(2);
    expect([...td.querySelectorAll("[data-chip-deadline]")].map((li) => li.textContent)).toEqual(["Idea a", "Idea b"]);
    const more = td.querySelector<HTMLAnchorElement>("[data-more]")!;
    expect(more.textContent).toBe("+2 more");
    expect(more.getAttribute("href")).toBe(`/dev/engagements?view=calendar&month=2026-10&day=${day}#day-list`);
    expect(within(td).getByRole("link", { name: "16 October: 4 deadlines" }).getAttribute("href")).toBe(
      more.getAttribute("href"),
    );
    // Phones: dots, at most three, decorative.
    expect(td.querySelectorAll("[aria-hidden='true'] > span")).toHaveLength(3);
  });

  it("puts each deadline on its Nairobi day, overdue in the error tone (said), the viewer's own turn warm", async () => {
    const late = deadline({ key: "stage:late", title: "Late one", due_on: "2026-10-09", overdue: true, mine: true });
    const mine = deadline({ key: "answer:mine", kind: "answer", title: "Mine", due_on: "2026-10-20", mine: true });
    const theirs = deadline({ key: "brief:theirs", kind: "brief", title: "Theirs", due_on: "2026-10-20" });
    const container = await month([late, mine, theirs]);
    const lateChip = cell(container, "2026-10-09").querySelector("[data-tone]")!;
    expect(lateChip.getAttribute("data-tone")).toBe("overdue");
    expect(lateChip.className).toContain("text-error");
    expect(lateChip.textContent).toBe("Overdue: Late one");
    const [first, second] = cell(container, "2026-10-20").querySelectorAll("[data-tone]");
    expect(first.getAttribute("data-tone")).toBe("mine");
    expect(first.querySelector(".bg-flourish")).not.toBeNull();
    expect(second.getAttribute("data-tone")).toBe("open");
    expect(cell(container, "2026-10-20").querySelector("[data-kind-mark='brief']")).not.toBeNull();
    // A day with nothing is not a link.
    expect(within(cell(container, "2026-10-21")).queryByRole("link")).toBeNull();
  });
});

describe("the list", () => {
  async function list(
    items: Deadline[],
    options: { clockFirst?: boolean; orgId?: string; side?: "developer" | "org" } = {},
  ) {
    return renderWithIntl(
      <>{await resolveServerTree(<DeadlineList items={items} now="2026-10-12T06:36:00.000Z" {...options} />)}</>,
    ).container;
  }

  it("draws the live clock on the next thing due only; the rest say their deadline in words", async () => {
    const container = await list(
      [deadline({ key: "stage:a" }), deadline({ key: "stage:b", due_on: "2026-10-20", business_days_left: 6 })],
      { clockFirst: true },
    );
    expect(container.querySelectorAll("[data-clock]")).toHaveLength(1);
    expect(container.querySelector("[data-deadline='stage:a'] [data-clock] time")?.getAttribute("datetime")).toBe(
      "P4DT14H23M",
    );
    expect(container.querySelector("[data-deadline='stage:b']")?.textContent).toContain(
      "6 business days left, due 20 Oct 2026",
    );
  });

  it("names the kind, links the title to its page and says the other party", async () => {
    const container = await list([
      deadline({ kind: "answer", key: "answer:x", title: "Answer the question", context: "SACCO B" }),
    ]);
    const row = container.querySelector<HTMLElement>("[data-deadline='answer:x']")!;
    expect(row.textContent).toContain("Answer by");
    expect(within(row).getByRole("link", { name: "Answer the question" }).getAttribute("href")).toBe(
      "/dev/engagements/0193f0c8-6a8f-7b4c-9d2e-3f4a5b6c7d8e",
    );
    expect(row.textContent).toContain("SACCO B");
  });

  it("puts each deadline in a calendar: the caller's .ics or the organisation's, and a Google Calendar entry", async () => {
    let container = await list([deadline({ key: "milestone:m1", kind: "milestone" })]);
    const ics = within(container).getByRole("link", { name: "Add to calendar: Maziwa baridi" });
    expect(ics.getAttribute("href")).toBe("/api/me/deadlines/milestone/m1/calendar.ics");
    expect(ics.hasAttribute("download")).toBe(true);
    const google = within(container).getByRole("link", { name: "Google Calendar: Maziwa baridi" });
    expect(google.getAttribute("href")).toMatch(/^https:\/\/calendar\.google\.com\/calendar\/render\?action=TEMPLATE/);
    expect(google.getAttribute("rel")).toBe("noopener noreferrer");
    cleanup();
    container = await list([deadline({ key: "event:e1", kind: "event" })], { orgId: "org-1" });
    expect(
      within(container)
        .getByRole("link", { name: /^Add to calendar/ })
        .getAttribute("href"),
    ).toBe("/api/orgs/org-1/deadlines/event/e1/calendar.ics");
  });

  it("carries one chip at most, Your turn on the viewer's own open steps; overdue words in the error tone", async () => {
    const container = await list([
      deadline({ key: "stage:mine", mine: true }),
      deadline({ key: "stage:late", mine: true, overdue: true, business_days_left: -2, due_on: "2026-10-08" }),
    ]);
    expect(container.querySelectorAll("[data-deadline='stage:mine'] [data-chip]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-deadline='stage:late'] [data-chip]")).toHaveLength(0);
    const late = container.querySelector("[data-deadline='stage:late'] [data-due]")!;
    expect(late.textContent).toBe("Overdue by 2 business days, was due 8 Oct 2026");
    expect(late.className).toContain("text-error");
  });

  it("says Our turn to an organisation, and never puts an event or a Brief's closing on anyone's turn", async () => {
    const container = await list(
      [
        deadline({ key: "stage:ours", mine: true }),
        deadline({ key: "event:e", kind: "event", mine: true }),
        deadline({ key: "brief:b", kind: "brief", mine: true }),
      ],
      { orgId: "org-1", side: "org" },
    );
    expect(container.querySelector("[data-deadline='stage:ours'] [data-chip]")?.textContent).toBe("Our turn");
    expect(
      container.querySelectorAll("[data-deadline='event:e'] [data-chip], [data-deadline='brief:b'] [data-chip]"),
    ).toHaveLength(0);
  });
});

describe("the Calendar view", () => {
  async function view(params: { month?: string; day?: string; orgId?: string } = {}) {
    const tree = await CalendarView({
      basePath: params.orgId ? "/org/engagements" : "/dev/engagements",
      orgId: params.orgId,
      month: params.month,
      day: params.day,
      side: params.orgId ? "org" : "developer",
      emptyHref: params.orgId ? "/org/inbox" : "/dev/discover",
    });
    return renderWithIntl(<>{await resolveServerTree(tree)}</>).container;
  }

  it("reads the month's grid and the overdue-plus-30-days list, for the organisation when it is one", async () => {
    await view({ orgId: "org-1" });
    expect(state.reads).toEqual([
      { span: { from: "2026-09-28", to: "2026-11-01" }, orgId: "org-1" },
      { span: { to: "2026-11-11" }, orgId: "org-1" },
    ]);
  });

  it("is one sentence and one action when nothing is due", async () => {
    const container = await view();
    const empty = container.querySelector<HTMLElement>("[data-deadlines='empty']")!;
    expect(empty.textContent).toContain("No deadlines in October 2026.");
    expect(within(empty).getAllByRole("link")).toHaveLength(1);
    expect(within(empty).getByRole("link", { name: "Find a problem to work on" }).getAttribute("href")).toBe(
      "/dev/discover",
    );
    expect(container.querySelector("table")).toBeNull();
  });

  it("lists what is overdue, then the next 30 days with the one live clock, and the page's ticker once", async () => {
    const late = deadline({ key: "stage:late", overdue: true, due_on: "2026-10-08", business_days_left: -2 });
    const soon = deadline({ key: "stage:soon" });
    state.grid = [late, soon];
    state.list = [late, soon];
    const container = await view();
    expect(screen.getByRole("heading", { level: 2, name: "Overdue" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Next 30 days" })).toBeTruthy();
    expect(container.querySelectorAll("[data-deadlines-group='overdue'] [data-deadline]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-deadlines-group='next'] [data-deadline]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-clock]")).toHaveLength(1);
    expect(container.querySelectorAll("script[data-clock-ticker]")).toHaveLength(1);
  });

  it("opens a day's list from the grid (?day=), the day marked; a day outside the grid is ignored", async () => {
    state.grid = [
      deadline({ key: "stage:a", due_on: "2026-10-16" }),
      deadline({ key: "brief:b", kind: "brief", due_on: "2026-10-16" }),
    ];
    let container = await view({ month: "2026-10", day: "2026-10-16" });
    expect(screen.getByRole("heading", { level: 2, name: "Deadlines on 16 October" })).toBeTruthy();
    expect(container.querySelectorAll("[data-deadlines-day] [data-deadline]")).toHaveLength(2);
    expect(container.querySelector("td[data-day='2026-10-16']")?.hasAttribute("data-selected")).toBe(true);
    cleanup();
    container = await view({ month: "2026-10", day: "2027-01-01" });
    expect(container.querySelector("[data-deadlines-day]")).toBeNull();
  });

  it("says why when the API refuses, with the one way on", async () => {
    state.refusal = "mfaSetup";
    const container = await view({ orgId: "org-1" });
    expect(container.textContent).toContain(en.tracker.refused.mfaSetup);
    expect(container.querySelector("[data-primary]")?.getAttribute("href")).toBe("/settings/security");
  });
});
