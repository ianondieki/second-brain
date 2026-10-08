import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import { ActivityCalendar } from "./ActivityCalendar";
import { buildGrid, level, parseActivity } from "./calendar";
import { activityFixture } from "./fixtures";

// D-67 (P25; REQ-UX-05, REQ-UX-06): the activity calendar. 26 weeks × 7 days, Monday first, in a five-step bloom
// scale; the grid is decorative for assistive technology beside a table of the days with any action; one sentence
// when there is nothing yet; no script.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("./fetch", () => ({ getActivity: async () => null }));
afterEach(cleanup);

const BUSY = { "2026-10-08": 6, "2026-10-01": 3, "2026-09-15": 1, "2026-05-04": 2 };

async function renderCalendar(activity = activityFixture(BUSY)) {
  const { container } = render(<>{await resolveServerTree(<ActivityCalendar activity={activity} />)}</>);
  return container;
}

describe("the grid", () => {
  it("is a column of seven days per week, Monday first, from the range's first week to this one", () => {
    const grid = buildGrid(activityFixture(BUSY));
    expect(grid.weeks).toHaveLength(27); // 182 days from a Friday to a Thursday touch 27 weeks
    expect(grid.weeks[0].slice(0, 4).every((cell) => cell.outside)).toBe(true); // before the range
    expect(grid.weeks[0][4]).toMatchObject({ date: "2026-04-10", outside: false });
    for (const week of grid.weeks) expect(week).toHaveLength(7);
    expect(new Date(`${grid.weeks[0][0].date}T00:00:00Z`).getUTCDay()).toBe(1); // a Monday
    const last = grid.weeks[26];
    expect(last[3]).toMatchObject({ date: "2026-10-08", count: 6, level: 4, outside: false }); // Thursday
    expect(last.slice(4).every((cell) => cell.outside)).toBe(true); // the days still to come
    expect(grid.weeks.flat().filter((cell) => !cell.outside)).toHaveLength(182);
  });

  it("names a month over the week it starts in, never two names closer than three weeks", () => {
    const { months } = buildGrid(activityFixture(BUSY));
    expect(months.length).toBeGreaterThanOrEqual(5);
    for (let i = 1; i < months.length; i += 1) expect(months[i].column - months[i - 1].column).toBeGreaterThanOrEqual(3);
  });

  it("puts a day on the five-step scale by its share of the busiest day", () => {
    expect([0, 1, 2, 3, 4, 6].map((n) => level(n, 6))).toEqual([0, 1, 2, 2, 3, 4]);
    expect(level(1, 1)).toBe(4);
    expect(level(3, 0)).toBe(0);
  });

  it("reads only the documented shape", () => {
    expect(parseActivity(activityFixture(BUSY))).not.toBeNull();
    expect(parseActivity({ ...activityFixture(), days: [{ date: "8 Oct", count: 1 }] })).toBeNull();
    expect(parseActivity({ ...activityFixture(), total: -1 })).toBeNull();
    expect(parseActivity({ ...activityFixture(), from: "2026-12-01" })).toBeNull();
    expect(parseActivity("nope")).toBeNull();
  });
});

describe("ActivityCalendar", () => {
  it("draws a cell per day with its level and a tip, hidden from assistive technology", async () => {
    const container = await renderCalendar();
    const grid = container.querySelector(".heat")!;
    expect(grid.getAttribute("aria-hidden")).toBe("true");
    const cells = grid.querySelectorAll(".heat-days > .heat-cell");
    expect(cells).toHaveLength(27 * 7);
    const today = [...cells].find((c) => c.getAttribute("data-tip") === "6 actions on 8 Oct 2026")!;
    expect(today.getAttribute("data-level")).toBe("4");
    expect([...grid.querySelectorAll(".heat-day")].map((l) => l.textContent)).toEqual(["Mon", "", "Wed", "", "Fri", "", ""]);
    expect(grid.querySelectorAll(".heat-months > .heat-label").length).toBeGreaterThanOrEqual(5);
  });

  it("gives the total, a line per kind and the Less to More legend", async () => {
    const container = await renderCalendar();
    expect(screen.getByText("12 actions in the last 26 weeks")).toBeTruthy();
    const kinds = screen.getByRole("list", { name: "What they were" });
    expect(within(kinds).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["6 versions registered", "6 messages"]);
    const legend = container.querySelector("[data-activity-legend]")!;
    expect(legend.textContent).toBe("LessMore");
    expect(legend.querySelectorAll("[data-level]")).toHaveLength(5);
  });

  it("gives assistive technology a table of the days with any action", async () => {
    await renderCalendar();
    const table = screen.getByRole("table", { name: "Your actions per day in the last 26 weeks, days with none left out" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(["4 May 20262", "15 Sep 20261", "1 Oct 20263", "8 Oct 20266"]);
    expect(within(table).getAllByRole("rowheader")).toHaveLength(4);
  });

  it("says one sentence when there is nothing yet", async () => {
    const container = await renderCalendar(activityFixture());
    expect(container.querySelector(".heat")).toBeNull();
    expect(container.textContent).toBe("Nothing yet: what you do on Wazo shows here, day by day.");
  });
});

// The scale, checked as the dataviz method checks an ordered ramp: one hue, lightness monotone with steps at least
// 0.06 apart (OKLab L), and the lightest non-empty step at 2:1 or more against the card, in light and dark.
describe("the scale", () => {
  const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
  const block = (start: string) => css.slice(css.indexOf(start), css.indexOf("}", css.indexOf(start)));
  const heat = (text: string) => [1, 2, 3, 4].map((n) => text.match(new RegExp(`--heat-${n}: (#[0-9a-f]{6})`))![1]);
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const rgb = (hex: string) => [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16) / 255));
  const luminance = (hex: string) => {
    const [r, g, b] = rgb(hex);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a: string, b: string) => {
    const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const oklabL = (hex: string) => {
    const [r, g, b] = rgb(hex);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  };

  it.each([
    ["light", block("\n:root {"), "#ffffff", -1],
    ["dark", block('\nhtml[data-theme="dark"] {'), "#19142a", 1],
  ] as const)("%s: monotone, distinct steps, the light end clear of the card", (_, text, card, direction) => {
    const steps = heat(text);
    const ls = steps.map(oklabL);
    for (let i = 1; i < ls.length; i += 1) expect(direction * (ls[i] - ls[i - 1])).toBeGreaterThanOrEqual(0.06);
    expect(contrast(steps[0], card)).toBeGreaterThanOrEqual(2);
    expect(contrast(steps[3], card)).toBeGreaterThanOrEqual(4.5);
  });

  it("is the same in the system's dark mode as in the chosen one", () => {
    const system = css.slice(css.indexOf("@media (prefers-color-scheme: dark)"));
    expect(heat(system)).toEqual(heat(block('\nhtml[data-theme="dark"] {')));
  });
});
