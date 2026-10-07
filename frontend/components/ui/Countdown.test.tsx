import { act, cleanup, render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import { Countdown } from "./Countdown";
import { TimeLeft } from "./TimeLeft";

// P23-3 (REQ-TRACK-03): the deadline countdown in days, hours and minutes, from the server's instant (the API's
// X-App-Now) plus the time the page has been open, never the browser's clock; a tick on each whole minute, paused
// while the tab is hidden; the screen's own words once the instant has passed; no live region.

const MIN = 60_000;
const NOW = "2026-10-10T06:36:00.000Z";
/** NOW plus 6 d 14 h 23 m. */
const UNTIL = new Date(Date.parse(NOW) + ((6 * 24 + 14) * 60 + 23) * MIN).toISOString();
const UNITS = ["{days} d {hours} h {minutes} m", "{hours} h {minutes} m", "{minutes} m"] as const;

function countdown(props: Partial<Parameters<typeof Countdown>[0]> = {}) {
  return render(
    <Countdown until={UNTIL} now={NOW} labelWhenPast="Overdue" units={UNITS} frame="{time} left" title="16 Oct 2026, 23:59 EAT" {...props} />,
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

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance", "Date"] });
  vi.setSystemTime(new Date(NOW));
});

afterEach(() => {
  cleanup();
  setHidden(false);
  vi.useRealTimers();
});

describe("Countdown", () => {
  it("says the time left in days, hours and minutes, in a <time> with the full instant, no live region", () => {
    const { container } = countdown();
    expect(text(container)).toBe("6 d 14 h 23 m left");
    expect(time(container)?.getAttribute("dateTime")).toBe(UNTIL);
    expect(time(container)?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect(container.querySelector("[aria-live], [role='status'], [role='timer']")).toBeNull();
  });

  it("drops the leading units that are zero", () => {
    expect(text(countdown({ until: new Date(Date.parse(NOW) + (14 * 60 + 5) * MIN).toISOString() }).container)).toBe("14 h 5 m left");
    cleanup();
    expect(text(countdown({ until: new Date(Date.parse(NOW) + 9 * MIN + 30_000).toISOString() }).container)).toBe("9 m left");
  });

  it("ticks on the next whole minute and every minute after, with one timer", () => {
    const { container } = countdown({ until: new Date(Date.parse(UNTIL) + 20_000).toISOString() });
    expect(text(container)).toBe("6 d 14 h 23 m left");
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(20_000)); // exactly 6 d 14 h 23 m left: still that figure
    expect(text(container)).toBe("6 d 14 h 23 m left");
    act(() => vi.advanceTimersByTime(1));
    expect(text(container)).toBe("6 d 14 h 22 m left");
    act(() => vi.advanceTimersByTime(MIN));
    expect(text(container)).toBe("6 d 14 h 21 m left");
    act(() => vi.advanceTimersByTime(60 * MIN));
    expect(text(container)).toBe("6 d 13 h 21 m left");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("starts again from a refreshed page's instant, without counting the old one's time twice", () => {
    const { container, rerender } = countdown();
    act(() => vi.advanceTimersByTime(10 * MIN));
    expect(text(container)).toBe("6 d 14 h 13 m left");
    const later = new Date(Date.parse(NOW) + 10 * MIN).toISOString();
    rerender(<Countdown until={UNTIL} now={later} labelWhenPast="Overdue" units={UNITS} frame="{time} left" title="t" />);
    expect(text(container)).toBe("6 d 14 h 13 m left");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("clears its timer when it unmounts", () => {
    const { unmount } = countdown();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("pauses while the tab is hidden and catches up when it is shown again", () => {
    const { container } = countdown();
    setHidden(true);
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(90 * MIN));
    expect(text(container)).toBe("6 d 14 h 23 m left");
    setHidden(false);
    expect(text(container)).toBe("6 d 12 h 53 m left");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("counts from the server's instant: a browser clock set years away changes nothing", () => {
    vi.setSystemTime(new Date("2031-03-01T00:00:00Z"));
    const { container } = countdown();
    expect(text(container)).toBe("6 d 14 h 23 m left");
    vi.setSystemTime(new Date("2019-01-01T00:00:00Z"));
    act(() => vi.advanceTimersByTime(MIN));
    expect(text(container)).toBe("6 d 14 h 22 m left");
  });

  it("says the screen's own words at or past the instant, and when the instant passes while open", () => {
    expect(text(countdown({ until: NOW }).container)).toBe("Overdue");
    cleanup();
    const { container } = countdown({ until: new Date(Date.parse(NOW) + 30_000).toISOString() });
    expect(text(container)).toBe("0 m left");
    act(() => vi.advanceTimersByTime(30_001));
    expect(text(container)).toBe("Overdue");
    expect(container.querySelector("[data-timer='past']")).not.toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("takes the warm mark under 24 hours only when the step is the viewer's", () => {
    const soon = new Date(Date.parse(NOW) + 23 * 60 * MIN).toISOString();
    const warm = countdown({ until: soon, tone: "warm" }).container;
    expect(warm.querySelector("[data-timer='warm']")).not.toBeNull();
    expect(text(warm)).toBe("23 h 0 m left");
    cleanup();
    expect(countdown({ until: soon, tone: "neutral" }).container.querySelector("[data-timer='open']")).not.toBeNull();
    cleanup();
    expect(countdown({ tone: "warm" }).container.querySelector("[data-timer='open']")).not.toBeNull();
  });

  it("places the figure inside the sentence's own words", () => {
    expect(text(countdown({ frame: "Submissions close in {time}" }).container)).toBe("Submissions close in 6 d 14 h 23 m");
  });
});

describe("TimeLeft (the words for Countdown)", () => {
  const withMessages = (locale: "en" | "sw") =>
    render(
      <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : sw} timeZone="Africa/Nairobi">
        <TimeLeft until={UNTIL} now={NOW} labelWhenPast="Overdue" />
        <TimeLeft until={UNTIL} now={NOW} labelWhenPast="Closed" sentence="closesIn" />
      </NextIntlClientProvider>,
    );

  it("words the figure in English with the instant in Nairobi time as its title", () => {
    const { container } = withMessages("en");
    const [left, closes] = container.querySelectorAll("[data-timer]");
    expect(left.textContent).toBe("6 d 14 h 23 m left");
    expect(closes.textContent).toBe("Submissions close in 6 d 14 h 23 m");
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
    const [left, closes] = container.querySelectorAll("[data-timer]");
    expect(left.textContent).toBe("Zimebaki siku 6 saa 14 dak 23");
    expect(closes.textContent).toBe("Mapendekezo yanafungwa baada ya siku 6 saa 14 dak 23");
  });
});
