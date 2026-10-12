import { act, cleanup, render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import { CLOCK_TICKER_SCRIPT } from "./ClockTicker";

// P26 (REQ-TRACK-03; REQ-UX-02): the live deadline clock, days, hours and minutes as figures (no leading zero units) in the figure face
// with their unit words, in one <time> carrying the duration and the full Nairobi instant, ticking on the minute from
// the page's app clock (the same clock as Countdown's, useAppClock.ts), warm under 24 hours only on the viewer's step,
// the screen's own word once past, no live region; the deadline in words as its line. P27: drawn on the server, kept
// by the page's ticker (ClockTicker.tsx, run here as the browser runs it), no React of its own.

const MIN = 60_000;
const NOW = "2026-10-10T06:36:00.000Z";
/** The end of 16 Oct 2026 in Nairobi: 6 d 14 h 23 m (and a fraction of a second) after NOW. */
const UNTIL = "2026-10-16T20:59:59.999Z";
const at = (minutes: number) => new Date(Date.parse(NOW) + minutes * MIN).toISOString();

// The app clock is the page's (the window's gap, shared by the ticker and Countdown's hook): each test starts without
// one, and with fresh copies of the modules.
let DeadlineClock: typeof import("./DeadlineClock").DeadlineClock;
let Countdown: typeof import("./Countdown").Countdown;

function withMessages(ui: ReactElement, locale: "en" | "sw" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : sw} timeZone="Africa/Nairobi">
      {ui}
    </NextIntlClientProvider>,
  );
}

const clock = () => document.querySelector<HTMLElement>("[data-clock]")!;
/** The page's ticker, run as the browser runs the inline script. */
const tick = () => new Function(CLOCK_TICKER_SCRIPT)();
const figures = () => [...document.querySelectorAll("[data-figure]")].map((figure) => figure.textContent);

beforeEach(async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date(NOW));
  vi.resetModules();
  delete (window as { __appGap?: number }).__appGap;
  delete (window as { __clocks?: () => void }).__clocks;
  ({ DeadlineClock } = await import("./DeadlineClock"));
  ({ Countdown } = await import("./Countdown"));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("DeadlineClock", () => {
  it("shows days, hours and minutes as three figures in one <time> with the duration and the Nairobi instant, its words under it", () => {
    withMessages(
      <DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" words="4 business days left, due 16 Oct 2026" />,
    );
    const time = clock().querySelector("time")!;
    expect(time.getAttribute("dateTime")).toBe("P6DT14H23M");
    expect(time.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect(time.querySelector("[data-clock-figures]")?.textContent).toBe("6 d 14 h 23 min");
    // Screen readers get the duration in words, the figures being its picture (aria-hidden).
    expect(time.querySelector(".sr-only")?.textContent).toBe("6 days 14 hours 23 minutes");
    expect(time.querySelector("[data-clock-figures]")?.getAttribute("aria-hidden")).toBe("true");
    expect(figures()).toEqual(["6", "14", "23"]);
    expect([...document.querySelectorAll("[data-unit]")].map((unit) => unit.textContent?.trim())).toEqual([
      "d",
      "h",
      "min",
    ]);
    // The figure face, tabular and bold; the unit words ink-soft.
    expect(clock().className).toContain("[&_[data-figure]]:font-figure");
    expect(clock().className).toContain("[&_[data-figure]]:tabular-nums");
    expect(clock().className).toContain("[&_[data-unit]]:text-ink-soft");
    expect(document.querySelector("[data-deadline-clock] p")?.textContent).toBe(
      "4 business days left, due 16 Oct 2026",
    );
    // No live region: a ticking figure is never announced; nothing hidden from screen readers.
    expect(document.querySelector("[aria-live], [role='status'], [role='timer']")).toBeNull();
    expect(document.querySelectorAll("[aria-hidden]")).toHaveLength(1); // only the figures, whose words sit beside them
  });

  it("puts each unit word where Swahili puts it, before its figure", () => {
    withMessages(<DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Imechelewa" />, "sw");
    expect(clock().querySelector("[data-clock-figures]")?.textContent).toBe("siku 6 saa 14 dak 23");
    expect(clock().querySelector("time .sr-only")?.textContent).toBe("siku 6 saa 14 dakika 23");
    expect(figures()).toEqual(["6", "14", "23"]);
  });

  it("takes its order and separators from the language's message, never from code", () => {
    const messages = {
      ...en,
      countdown: {
        ...en.countdown,
        clockDays: "<f>{minutes}</f><u>m</u> / <f>{hours}</f><u>h</u> / <f>{days}</f><u>d</u>",
      },
    };
    render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="Africa/Nairobi">
        <DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" />
      </NextIntlClientProvider>,
    );
    expect(clock().querySelector("[data-clock-figures]")?.textContent).toBe("23m / 14h / 6d");
    expect(figures()).toEqual(["23", "14", "6"]);
    expect(clock().querySelector("time")?.getAttribute("datetime")).toBe("P6DT14H23M");
  });

  it("leaves out the leading units that are zero (the duration stays whole), and comes in two sizes", () => {
    withMessages(<DeadlineClock until={at(9)} now={NOW} labelWhenPast="Overdue" size="lg" />);
    expect(figures()).toEqual(["9"]);
    expect(clock().querySelector("[data-clock-figures]")?.textContent).toBe("9 min");
    expect(clock().querySelector("time .sr-only")?.textContent).toBe("9 minutes");
    expect(clock().querySelector("time")?.getAttribute("dateTime")).toBe("P0DT0H9M");
    expect(document.querySelector("[data-deadline-clock]")?.getAttribute("data-deadline-clock")).toBe("lg");
    expect(clock().className).toContain("sm:[&_[data-figure]]:text-[2.5rem]");
    cleanup();
    withMessages(<DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" />);
    expect(document.querySelector("[data-deadline-clock]")?.getAttribute("data-deadline-clock")).toBe("sm");
    expect(clock().className).toContain("[&_[data-figure]]:text-[1.375rem]");
  });

  it("ticks on the minute: the server's figure first, then the minutes figure moves down each whole minute, one timer", () => {
    withMessages(<DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" />);
    expect(figures()).toEqual(["6", "14", "23"]);
    // No timer of its own: the page's ticker keeps it.
    expect(vi.getTimerCount()).toBe(0);
    tick();
    expect(figures()).toEqual(["6", "14", "23"]);
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(MIN));
    expect(figures()).toEqual(["6", "14", "22"]);
    expect(clock().querySelector("time")?.getAttribute("dateTime")).toBe("P6DT14H22M");
    act(() => vi.advanceTimersByTime(23 * MIN));
    expect(figures()).toEqual(["6", "13", "59"]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("takes the warm look under 24 hours only on the viewer's step", () => {
    withMessages(<DeadlineClock until={at(14 * 60 + 23)} now={NOW} labelWhenPast="Overdue" mine />);
    expect(clock().getAttribute("data-clock")).toBe("warm");
    // Under a day: two figures, no "0 d"; the duration stays whole.
    expect(figures()).toEqual(["14", "23"]);
    expect(clock().querySelector("[data-clock-figures]")?.textContent).toBe("14 h 23 min");
    expect(clock().querySelector("time")?.getAttribute("dateTime")).toBe("P0DT14H23M");
    expect(clock().className).toContain("[&[data-clock=warm]_[data-figure]]:text-warm");
    cleanup();
    withMessages(<DeadlineClock until={at(23 * 60)} now={NOW} labelWhenPast="Overdue" />);
    expect(clock().getAttribute("data-clock")).toBe("open");
    cleanup();
    withMessages(<DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" mine />);
    expect(clock().getAttribute("data-clock")).toBe("open");
  });

  it("says the screen's own word at or past the instant (never a negative time), and when it passes while open", () => {
    withMessages(<DeadlineClock until={NOW} now={NOW} labelWhenPast="Overdue" />);
    expect(clock().textContent).toBe("Overdue");
    expect(clock().getAttribute("data-clock")).toBe("past");
    expect(document.querySelector("time")).toBeNull();
    cleanup();
    withMessages(<DeadlineClock until={at(1)} now={NOW} labelWhenPast="Overdue" />);
    expect(figures()).toEqual(["1"]);
    tick();
    act(() => vi.advanceTimersByTime(MIN + 1));
    expect(clock().textContent).toBe("Overdue");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reads the same app clock as Countdown: a page drawn from the cache is put right at once, and both agree", () => {
    withMessages(
      <Countdown
        until={UNTIL}
        now={NOW}
        labelWhenPast="Overdue"
        units={["", "99 d", "{hours} h", "{minutes} min"]}
        frame="{time}"
        title=""
      />,
    );
    cleanup();
    act(() => vi.advanceTimersByTime(30 * MIN));
    // A list drawn half an hour ago, restored: the server's figure first (hydration), then the app clock's.
    withMessages(
      <>
        <DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" />
        <Countdown
          until={UNTIL}
          now={NOW}
          labelWhenPast="Overdue"
          units={["", "99 days {hours} h {minutes} min", "{hours} h", "{minutes} min"]}
          frame="{time}"
          title=""
        />
      </>,
    );
    expect(figures()).toEqual(["6", "14", "23"]);
    // The ticker runs where the page is parsed: the clock put right at once, then Countdown's hook on hydration.
    tick();
    expect(figures()).toEqual(["6", "13", "53"]);
    act(() => vi.advanceTimersByTime(0));
    expect(figures()).toEqual(["6", "13", "53"]);
    expect(document.querySelector("[data-timer] time")?.getAttribute("dateTime")).toBe("P6DT13H53M");
  });
});
