import { act, cleanup, render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import type { CountdownProps } from "./Countdown";

// P23-3 (REQ-TRACK-03): the deadline countdown in days, hours and minutes, counted on the app clock: the browser's
// clock less its gap to the freshest server instant (the API's X-App-Now), so a page from the router's cache, a
// restored tab and time asleep all read right and a browser clock set wrong changes nothing; a tick on each whole
// minute, paused while the tab is hidden; the screen's own words once the instant has passed; no live region.

const MIN = 60_000;
const NOW = "2026-10-10T06:36:00.000Z";
/** NOW plus 6 d 14 h 23 m. */
const UNTIL = new Date(Date.parse(NOW) + ((6 * 24 + 14) * 60 + 23) * MIN).toISOString();
const UNITS = ["1 day {hours} h {minutes} min", "99 days {hours} h {minutes} min", "{hours} h {minutes} min", "{minutes} min"] as const;
const at = (minutes: number) => new Date(Date.parse(NOW) + minutes * MIN).toISOString();

// The app clock is the module's own (one per page): each test loads a fresh copy.
let Countdown: typeof import("./Countdown").Countdown;
let TimeLeft: typeof import("./TimeLeft").TimeLeft;

function countdown(props: Partial<CountdownProps> = {}) {
  return render(
    <Countdown until={UNTIL} now={NOW} labelWhenPast="Overdue" units={UNITS} frame="in {time}" title="16 Oct 2026, 23:59 EAT" {...props} />,
  );
}

const text = (container: HTMLElement) => container.textContent;
const time = (container: HTMLElement) => container.querySelector("time");

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date(NOW));
  vi.resetModules();
  ({ Countdown } = await import("./Countdown"));
  ({ TimeLeft } = await import("./TimeLeft"));
});

afterEach(() => {
  cleanup();
  setHidden(false);
  vi.useRealTimers();
});

describe("Countdown", () => {
  it("says the time left in days, hours and minutes: a <time> with the duration, the full instant as its title, no live region", () => {
    const { container } = countdown();
    expect(text(container)).toBe("in 6 days 14 h 23 min");
    expect(time(container)?.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(time(container)?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect(container.querySelector("[aria-live], [role='status'], [role='timer']")).toBeNull();
  });

  it("says one day in the singular and drops the leading units that are zero", () => {
    expect(text(countdown({ until: at(24 * 60 + 5) }).container)).toBe("in 1 day 0 h 5 min");
    cleanup();
    expect(text(countdown({ until: at(14 * 60 + 5) }).container)).toBe("in 14 h 5 min");
    cleanup();
    const nine = countdown({ until: new Date(Date.parse(NOW) + 9 * MIN + 30_000).toISOString() }).container;
    expect(text(nine)).toBe("in 9 min");
    expect(time(nine)?.getAttribute("dateTime")).toBe("P0DT0H9M");
  });

  it("waits for the next whole minute before its first tick (the server's figure stays), then ticks every minute with one timer", () => {
    const { container } = countdown({ until: new Date(Date.parse(UNTIL) + 20_000).toISOString() });
    expect(text(container)).toBe("in 6 days 14 h 23 min");
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(20_000)); // exactly 6 d 14 h 23 m left: still that figure
    expect(text(container)).toBe("in 6 days 14 h 23 min");
    act(() => vi.advanceTimersByTime(1));
    expect(text(container)).toBe("in 6 days 14 h 22 min");
    act(() => vi.advanceTimersByTime(MIN));
    expect(text(container)).toBe("in 6 days 14 h 21 min");
    act(() => vi.advanceTimersByTime(60 * MIN));
    expect(text(container)).toBe("in 6 days 13 h 21 min");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("puts right at once a page drawn earlier (the router's cache, back and forward): the freshest instant wins", () => {
    countdown();
    cleanup();
    act(() => vi.advanceTimersByTime(30 * MIN));
    // The same page again, with the instant it was drawn at half an hour ago.
    const { container } = countdown();
    expect(text(container)).toBe("in 6 days 14 h 23 min"); // the server's figure first: hydration matches its HTML
    act(() => vi.advanceTimersByTime(0));
    expect(text(container)).toBe("in 6 days 13 h 53 min");
    // A newer page's instant moves the app clock on; an older one never moves it back.
    cleanup();
    const later = countdown({ now: at(40) }).container;
    expect(text(later)).toBe("in 6 days 13 h 43 min");
    cleanup();
    const stale = countdown({ now: at(0) }).container;
    act(() => vi.advanceTimersByTime(0));
    expect(text(stale)).toBe("in 6 days 13 h 43 min");
  });

  it("never sets the clock back for an instant newer than the last but behind the clock (a page prefetched earlier)", () => {
    countdown();
    cleanup();
    act(() => vi.advanceTimersByTime(30 * MIN));
    // Fetched at NOW + 20 min, first shown at NOW + 30 min.
    const { container } = countdown({ now: at(20) });
    expect(text(container)).toBe("in 6 days 14 h 3 min"); // the server's figure first: hydration matches its HTML
    act(() => vi.advanceTimersByTime(0));
    expect(text(container)).toBe("in 6 days 13 h 53 min");
  });

  it("counts the time asleep: the browser's clock moves on while no timer runs, and showing the tab puts it right", () => {
    const { container } = countdown();
    vi.setSystemTime(new Date(Date.parse(NOW) + 3 * 60 * MIN)); // three hours asleep, no timer fired
    setHidden(false);
    expect(text(container)).toBe("in 6 days 11 h 23 min");
    act(() => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("pageshow"));
    });
    expect(text(container)).toBe("in 6 days 11 h 23 min");
  });

  it("clears its timer and listeners when it unmounts", () => {
    const { unmount } = countdown();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("pauses while the tab is hidden and catches up when it is shown again", () => {
    const { container } = countdown();
    setHidden(true);
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(90 * MIN));
    expect(text(container)).toBe("in 6 days 14 h 23 min");
    setHidden(false);
    expect(text(container)).toBe("in 6 days 12 h 53 min");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("counts on the app clock: a browser clock set years away changes nothing", () => {
    vi.setSystemTime(new Date("2031-03-01T00:00:00Z"));
    const { container } = countdown();
    expect(text(container)).toBe("in 6 days 14 h 23 min");
    act(() => vi.advanceTimersByTime(MIN));
    expect(text(container)).toBe("in 6 days 14 h 22 min");
  });

  it("says the screen's own words at or past the instant, and when the instant passes while open", () => {
    expect(text(countdown({ until: NOW }).container)).toBe("Overdue");
    cleanup();
    const { container } = countdown({ until: new Date(Date.parse(NOW) + 30_000).toISOString() });
    expect(text(container)).toBe("in 0 min");
    act(() => vi.advanceTimersByTime(30_001));
    expect(text(container)).toBe("Overdue");
    expect(container.querySelector("[data-timer='past']")).not.toBeNull();
    expect(container.querySelector("time")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("takes the warm look under 24 hours only when the step is the viewer's", () => {
    const soon = at(23 * 60);
    const warm = countdown({ until: soon, tone: "warm" }).container;
    expect(warm.querySelector("[data-timer='warm']")).not.toBeNull();
    expect(text(warm)).toBe("in 23 h 0 min");
    cleanup();
    expect(countdown({ until: soon, tone: "neutral" }).container.querySelector("[data-timer='open']")).not.toBeNull();
    cleanup();
    expect(countdown({ tone: "warm" }).container.querySelector("[data-timer='open']")).not.toBeNull();
  });

  it("places the figure inside the sentence's own words", () => {
    expect(text(countdown({ frame: "Proposals close in {time}" }).container)).toBe("Proposals close in 6 days 14 h 23 min");
  });
});

describe("TimeLeft (the words for Countdown)", () => {
  const withMessages = (locale: "en" | "sw") =>
    render(
      <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : sw} timeZone="Africa/Nairobi">
        <TimeLeft until={UNTIL} now={NOW} labelWhenPast="Overdue" />
        <TimeLeft until={UNTIL} now={NOW} labelWhenPast="Closed" sentence="closesIn" />
        <TimeLeft until={UNTIL} now={NOW} labelWhenPast="Was due" sentence="dueIn" date="16 Oct 2026" />
        <TimeLeft until={at(24 * 60 + 2)} now={NOW} labelWhenPast="Overdue" />
      </NextIntlClientProvider>,
    );

  it("words the figure in English, one day in the singular, with the instant in Nairobi time as its title", () => {
    const { container } = withMessages("en");
    const [left, closes, due, one] = container.querySelectorAll("[data-timer]");
    expect(left.textContent).toBe("in 6 days 14 h 23 min");
    expect(closes.textContent).toBe("Proposals close in 6 days 14 h 23 min");
    expect(due.textContent).toBe("Due 16 Oct 2026 · in\u00a06 days 14 h 23 min"); // "in" stays with the time
    expect(one.textContent).toBe("in 1 day 0 h 2 min");
    // UNTIL is 2026-10-16T20:59Z: 23:59 on 16 Oct in Nairobi.
    expect(left.querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    // Tabular figures; the warm look (the saffron mark, a pseudo-element, and the warm figure) keyed on data-timer.
    expect(left.className).toContain("tabular-nums");
    expect(left.className).toContain("data-[timer=warm]:before:bg-flourish");
    expect(left.className).toContain("[&[data-timer=warm]>time]:text-warm");
    expect(left.querySelector("[aria-hidden]")).toBeNull();
  });

  it("words the figure in Swahili", () => {
    const { container } = withMessages("sw");
    const [left, closes, due] = container.querySelectorAll("[data-timer]");
    expect(left.textContent).toBe("baada ya siku 6 saa 14 dak 23");
    expect(closes.textContent).toBe("Mapendekezo yatafungwa baada ya siku 6 saa 14 dak 23");
    expect(due.textContent).toBe("Inatakiwa 16 Oct 2026 · baada ya\u00a0siku 6 saa 14 dak 23");
  });
});
