import { cleanup, render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { gzipSync } from "node:zlib";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import { ClockFigures } from "./ClockFigures";
import { readFileSync } from "node:fs";

import { CLOCK_BOOT_SCRIPT, CLOCK_TICKER_SCRIPT, CLOCK_TICKER_TYPE, ClockTicker } from "./ClockTicker";
import { DeadlineClock, DeadlineLine } from "./DeadlineClock";

// P27 (REQ-TRACK-03, REQ-UX-05): the page's clock ticker. The server draws every clock whole; one script for the page
// (no React, constant text, at most 1.5 KB gzipped, carried as a data block) moves them all on the minute boundary from
// the app clock, with the screen-reader words, the <time>'s duration and the warm and past states; it pauses while the
// tab is hidden and runs again when it is shown, restored or focused. The root layout's boot runs it once the document
// is parsed, and again for clocks a navigation adds or a refresh draws again. Offline, the clocks are hidden.

const MIN = 60_000;
const NOW = "2026-10-10T06:36:00.000Z";
/** The end of 16 Oct 2026 in Nairobi: 6 d 14 h 23 m (and a fraction of a second) after NOW. */
const UNTIL = "2026-10-16T20:59:59.999Z";
const at = (ms: number) => new Date(Date.parse(NOW) + ms).toISOString();

type Page = { __clocks?: () => void };
const page = window as unknown as Page;

/** The page's ticker, run as the boot runs it (a copy of the data block, put in the head). */
const tick = () => new Function(CLOCK_TICKER_SCRIPT)();

function withMessages(ui: ReactElement, locale: "en" | "sw" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : sw} timeZone="Africa/Nairobi">
      {ui}
    </NextIntlClientProvider>,
  );
}

const clockOf = (id: string) => document.querySelector<HTMLElement>(`[data-testid='${id}'] [data-clock]`)!;
const figures = (id: string) => [...clockOf(id).querySelectorAll("[data-figure]")].map((figure) => figure.textContent);
const duration = (id: string) => clockOf(id).querySelector("time")?.getAttribute("datetime");
const words = (id: string) => clockOf(id).querySelector("time .sr-only")?.textContent;

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  // As the browser fires it: at the document, bubbling.
  document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date(NOW));
  delete page.__clocks;
});

afterEach(() => {
  cleanup();
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
  delete page.__clocks;
  vi.useRealTimers();
  document.head.querySelectorAll("script").forEach((script) => script.remove());
});

/** A page fragment: a card's clock six days out, and the viewer's own clock two minutes from its end, warm. */
function twoClocks(locale: "en" | "sw" = "en") {
  const past = locale === "en" ? "Overdue" : "Imechelewa";
  return withMessages(
    <main>
      <div data-testid="far">
        <DeadlineClock until={UNTIL} now={NOW} labelWhenPast={past} />
      </div>
      <div data-testid="near">
        <DeadlineClock until={at(2 * MIN - 1)} now={NOW} labelWhenPast={past} mine />
      </div>
      <ClockTicker />
    </main>,
    locale,
  );
}

describe("the clock ticker", () => {
  it("is one small constant script, no React, carried by the page as a data block no browser runs", () => {
    expect(gzipSync(CLOCK_TICKER_SCRIPT).length).toBeLessThanOrEqual(1_500);
    // No English (or any language) in it: the words come from the clocks' own attributes and from Intl.
    for (const word of ["Overdue", "Imechelewa", " min", "siku", "dak ", "in {time}", "baada", "EAT"]) {
      expect(CLOCK_TICKER_SCRIPT).not.toContain(word);
    }
    expect(CLOCK_TICKER_SCRIPT).not.toMatch(/<\/script/i);
    twoClocks();
    const scripts = document.querySelectorAll("script[data-clock-ticker]");
    expect(scripts).toHaveLength(1);
    expect(scripts[0].getAttribute("type")).toBe(CLOCK_TICKER_TYPE);
    expect(CLOCK_TICKER_TYPE).not.toMatch(/javascript|ecmascript|module/);
    expect(scripts[0].textContent).toBe(CLOCK_TICKER_SCRIPT);
  });

  it("moves every clock on the next minute boundary: the figures, the words and the duration, one timer for the page", () => {
    twoClocks();
    expect(figures("far")).toEqual(["6", "14", "23"]);
    expect(figures("near")).toEqual(["1"]);
    tick();
    // The server's figures stand until the minute turns.
    expect(figures("far")).toEqual(["6", "14", "23"]);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(MIN - 1);
    expect(figures("far")).toEqual(["6", "14", "23"]);
    vi.advanceTimersByTime(1);
    expect(figures("far")).toEqual(["6", "14", "22"]);
    expect(duration("far")).toBe("P6DT14H22M");
    expect(words("far")).toBe("6 days 14 hours 22 minutes");
    expect(clockOf("far").getAttribute("data-clock")).toBe("open");
    expect(figures("near")).toEqual(["0"]);
    expect(duration("near")).toBe("P0DT0H0M");
    expect(words("near")).toBe("0 minutes");
    expect(clockOf("near").getAttribute("data-clock")).toBe("warm");
    // The figures stay a picture of the words (aria-hidden), the look keyed as before.
    expect(clockOf("far").querySelector("[data-clock-figures]")?.textContent).toBe("6 d 14 h 22 min");
    expect(clockOf("far").querySelector("[data-clock-figures]")?.getAttribute("aria-hidden")).toBe("true");
    expect([...clockOf("far").querySelectorAll("[data-unit]")].map((unit) => unit.textContent)).toEqual([
      " d",
      " h",
      " min",
    ]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("shows the past words when a clock crosses its instant, without the warm tone, and stops counting it", () => {
    twoClocks();
    tick();
    vi.advanceTimersByTime(2 * MIN);
    expect(clockOf("near").textContent).toBe("Overdue");
    expect(clockOf("near").getAttribute("data-clock")).toBe("past");
    expect(clockOf("near").querySelector("time")).toBeNull();
    // The other goes on; one timer, for it alone.
    expect(figures("far")).toEqual(["6", "14", "21"]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("keeps a clock that is not the viewer's open as it crosses 24 hours (never warm)", () => {
    withMessages(
      <div data-testid="day">
        <DeadlineClock until={at(1_440 * MIN + 30_000)} now={NOW} labelWhenPast="Overdue" />
      </div>,
    );
    expect(figures("day")).toEqual(["1", "0", "0"]);
    tick();
    vi.advanceTimersByTime(30_001);
    expect(figures("day")).toEqual(["23", "59"]);
    expect(clockOf("day").getAttribute("data-clock")).toBe("open");
  });

  it("turns the viewer's own clock warm as it crosses 24 hours, and not before", () => {
    withMessages(
      <div data-testid="day">
        <DeadlineClock until={at(1_440 * MIN + 30_000)} now={NOW} labelWhenPast="Overdue" mine />
      </div>,
    );
    tick();
    expect(clockOf("day").getAttribute("data-clock")).toBe("open");
    vi.advanceTimersByTime(30_000);
    expect(figures("day")).toEqual(["1", "0", "0"]);
    expect(clockOf("day").getAttribute("data-clock")).toBe("open");
    vi.advanceTimersByTime(1);
    expect(figures("day")).toEqual(["23", "59"]);
    expect(clockOf("day").getAttribute("data-clock")).toBe("warm");
  });

  it("keeps the viewer's own clock open while more than a day is left, tick after tick", () => {
    withMessages(
      <div data-testid="week">
        <DeadlineClock until={UNTIL} now={NOW} labelWhenPast="Overdue" mine />
      </div>,
    );
    tick();
    vi.advanceTimersByTime(MIN);
    expect(figures("week")).toEqual(["6", "14", "22"]);
    expect(clockOf("week").getAttribute("data-clock")).toBe("open");
    vi.advanceTimersByTime(3 * 60 * MIN);
    expect(figures("week")).toEqual(["6", "11", "22"]);
    expect(clockOf("week").getAttribute("data-clock")).toBe("open");
  });

  it("says the past words at the very instant (nothing left is past, not 0 min), and schedules nothing", () => {
    withMessages(
      <div data-testid="edge">
        <DeadlineClock until={at(2 * MIN)} now={NOW} labelWhenPast="Overdue" mine />
      </div>,
    );
    tick();
    expect(figures("edge")).toEqual(["2"]);
    expect(vi.getTimerCount()).toBe(1);
    // The window comes back at exactly the instant: no time is left.
    vi.setSystemTime(new Date(Date.parse(NOW) + 2 * MIN));
    window.dispatchEvent(new Event("focus"));
    expect(clockOf("edge").textContent).toBe("Overdue");
    expect(clockOf("edge").getAttribute("data-clock")).toBe("past");
    expect(clockOf("edge").querySelector("time")).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("writes what the server would have drawn at that minute, in either language", () => {
    for (const locale of ["en", "sw"] as const) {
      twoClocks(locale);
      tick();
      vi.advanceTimersByTime(23 * MIN + 30_000);
      const ticked = [clockOf("far").outerHTML, clockOf("near").outerHTML];
      cleanup();
      // Drawn by the server now: the same markup, data-now aside.
      twoClocksAt(locale, new Date(Date.now()).toISOString());
      const drawn = [clockOf("far").outerHTML, clockOf("near").outerHTML];
      const sansNow = (html: string) => html.replace(/ data-now="[^"]*"/, "");
      expect(ticked.map(sansNow)).toEqual(drawn.map(sansNow));
      cleanup();
      delete page.__clocks;
      vi.setSystemTime(new Date(NOW));
    }
  });

  it("pauses while the tab is hidden and puts every clock right as soon as it is shown again", () => {
    twoClocks();
    tick();
    setHidden(true);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * MIN);
    expect(figures("far")).toEqual(["6", "14", "23"]);
    setHidden(false);
    expect(figures("far")).toEqual(["6", "14", "13"]);
    expect(clockOf("near").getAttribute("data-clock")).toBe("past");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("runs again on pageshow and focus (a page restored, a window come back)", () => {
    twoClocks();
    tick();
    // The device slept: the browser's clock moved on with no timer run.
    vi.setSystemTime(new Date(Date.parse(NOW) + 5 * MIN));
    window.dispatchEvent(new Event("pageshow"));
    expect(figures("far")).toEqual(["6", "14", "18"]);
    vi.setSystemTime(new Date(Date.parse(NOW) + 7 * MIN));
    window.dispatchEvent(new Event("focus"));
    expect(figures("far")).toEqual(["6", "14", "16"]);
  });

  it("keeps the app clock: a browser clock set wrong changes nothing, a page drawn earlier is put right at once", () => {
    // The browser's clock is a year ahead: the gap absorbs it.
    vi.setSystemTime(new Date(Date.parse(NOW) + 365 * 1_440 * MIN));
    twoClocks();
    tick();
    expect(figures("far")).toEqual(["6", "14", "23"]);
    vi.advanceTimersByTime(MIN);
    expect(figures("far")).toEqual(["6", "14", "22"]);
    cleanup();
    // Half an hour on, a list drawn from the cache (its instant the old one) is put right as soon as it runs.
    vi.advanceTimersByTime(30 * MIN);
    twoClocks();
    expect(figures("far")).toEqual(["6", "14", "23"]);
    tick(); // the script rendered again: it runs the clocks again
    expect(figures("far")).toEqual(["6", "13", "52"]);
    expect(vi.getTimerCount()).toBe(1);
  });

  it("keeps a sentence clock the same way (its words from Intl, the sentence the language's own)", () => {
    withMessages(
      <p data-testid="line">
        <DeadlineLine until={UNTIL} now={NOW} labelWhenPast="Overdue" />
      </p>,
    );
    expect(clockOf("line").textContent).toBe("in 6\u00a0days 14\u00a0hours 23\u00a0minutes");
    tick();
    vi.advanceTimersByTime(MIN);
    expect(clockOf("line").textContent).toBe("in 6\u00a0days 14\u00a0hours 22\u00a0minutes");
    expect(duration("line")).toBe("P6DT14H22M");
    expect(clockOf("line").querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    cleanup();
    withMessages(
      <p data-testid="line">
        <DeadlineLine until={at(MIN)} now={NOW} labelWhenPast="Imechelewa" />
      </p>,
      "sw",
    );
    expect(clockOf("line").textContent).toBe("baada ya dakika\u00a01");
    vi.advanceTimersByTime(MIN);
    expect(clockOf("line").textContent).toBe("Imechelewa");
    expect(clockOf("line").getAttribute("data-clock")).toBe("past");
  });

  it("escapes the words it writes (a message is text, never markup)", () => {
    render(
      <div data-testid="odd">
        <ClockFigures
          until={UNTIL}
          now={NOW}
          labelWhenPast="Late"
          formats={[
            "<f>{days}</f><u> d&amp;</u> <f>{hours}</f><u> h</u> <f>{minutes}</f><u> <b>m</u>",
            "<f>{hours}</f>",
            "<f>{minutes}</f>",
          ]}
          title={'"16 Oct"'}
          locale="en"
        />
      </div>,
    );
    tick();
    vi.advanceTimersByTime(MIN);
    expect(clockOf("odd").querySelectorAll("b")).toHaveLength(0);
    expect(clockOf("odd").querySelector("time")?.getAttribute("title")).toBe('"16 Oct"');
  });
});

describe("sentence clocks (DeadlineLine) on the ticker", () => {
  const lines = (locale: "en" | "sw") =>
    withMessages(
      <>
        <p data-testid="in">
          <DeadlineLine until={UNTIL} now={NOW} labelWhenPast="Overdue" />
        </p>
        <p data-testid="closes">
          <DeadlineLine until={UNTIL} now={NOW} labelWhenPast="Closed" sentence="closesIn" />
        </p>
        <p data-testid="one">
          <DeadlineLine until={at((24 * 60 + 2) * MIN)} now={NOW} labelWhenPast="Overdue" />
        </p>
      </>,
      locale,
    );

  it("says the time left in the language's own words, one day in the singular, the Nairobi instant as its title", () => {
    lines("en");
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 14\u00a0hours 23\u00a0minutes");
    expect(clockOf("closes").textContent).toBe("Proposals close in 6\u00a0days 14\u00a0hours 23\u00a0minutes");
    expect(clockOf("one").textContent).toBe("in 1\u00a0day 0\u00a0hours 2\u00a0minutes");
    expect(clockOf("in").querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    expect(duration("in")).toBe("P6DT14H23M");
    // Tabular figures; the warm look (the saffron mark, a pseudo-element, and the warm time) keyed on data-clock.
    expect(clockOf("in").className).toContain("tabular-nums");
    expect(clockOf("in").className).toContain("data-[clock=warm]:before:bg-flourish");
    expect(clockOf("in").className).toContain("[&[data-clock=warm]>time]:text-warm");
    // The words are the clock: nothing hidden, no live region.
    expect(document.querySelector("[aria-hidden], [aria-live], [role='timer']")).toBeNull();
    cleanup();
    lines("sw");
    expect(clockOf("in").textContent).toBe("baada ya siku\u00a06 saa\u00a014 dakika\u00a023");
    expect(clockOf("closes").textContent).toBe(
      "Mapendekezo yatafungwa baada ya siku\u00a06 saa\u00a014 dakika\u00a023",
    );
  });

  it("writes what the server would have drawn at that minute, each unit held together by no-break spaces", () => {
    for (const locale of ["en", "sw"] as const) {
      const line = (now: string) =>
        withMessages(
          <p data-testid="in">
            <DeadlineLine until={UNTIL} now={now} labelWhenPast="Overdue" />
          </p>,
          locale,
        );
      line(NOW);
      tick();
      vi.advanceTimersByTime(23 * MIN + 30_000);
      const ticked = clockOf("in").outerHTML;
      // The sentence wraps between units only ("6 days" | "14 hours", "siku 6" | "saa 14").
      expect(clockOf("in").querySelector("time")?.textContent?.split(" ")).toHaveLength(3);
      cleanup();
      line(new Date(Date.now()).toISOString());
      const sansNow = (html: string) => html.replace(/ data-now="[^"]*"/, "");
      expect(sansNow(ticked)).toBe(sansNow(clockOf("in").outerHTML));
      cleanup();
      delete page.__clocks;
      vi.setSystemTime(new Date(NOW));
    }
  });

  it("drops the leading units that are zero", () => {
    withMessages(
      <>
        <p data-testid="hours">
          <DeadlineLine until={at((14 * 60 + 5) * MIN)} now={NOW} labelWhenPast="Overdue" />
        </p>
        <p data-testid="nine">
          <DeadlineLine until={at(9 * MIN + 30_000)} now={NOW} labelWhenPast="Overdue" />
        </p>
      </>,
    );
    expect(clockOf("hours").textContent).toBe("in 14\u00a0hours 5\u00a0minutes");
    expect(clockOf("nine").textContent).toBe("in 9\u00a0minutes");
    expect(duration("nine")).toBe("P0DT0H9M");
  });

  it("keeps the server's figure until the next whole minute, then ticks each minute with one timer", () => {
    withMessages(
      <p data-testid="in">
        <DeadlineLine until={at(((6 * 24 + 14) * 60 + 23) * MIN + 20_000)} now={NOW} labelWhenPast="Overdue" />
      </p>,
    );
    tick();
    vi.advanceTimersByTime(20_000); // exactly 6 d 14 h 23 m left: still that figure
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 14\u00a0hours 23\u00a0minutes");
    vi.advanceTimersByTime(1);
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 14\u00a0hours 22\u00a0minutes");
    vi.advanceTimersByTime(61 * MIN);
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 13\u00a0hours 21\u00a0minutes");
    expect(vi.getTimerCount()).toBe(1);
  });

  it("lets the freshest server instant win: a page drawn later moves the clock on, one drawn earlier never moves it back", () => {
    const line = (now: string) =>
      withMessages(
        <p data-testid="in">
          <DeadlineLine until={UNTIL} now={now} labelWhenPast="Overdue" />
        </p>,
      );
    line(NOW);
    tick();
    cleanup();
    vi.advanceTimersByTime(30 * MIN);
    // Prefetched at NOW + 20 min, first shown at NOW + 30 min: the app clock's time, not the page's.
    line(at(20 * MIN));
    tick();
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 13\u00a0hours 53\u00a0minutes");
    cleanup();
    // A page drawn at NOW + 40 min (ahead of the app clock) moves it on.
    line(at(40 * MIN));
    tick();
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 13\u00a0hours 43\u00a0minutes");
    cleanup();
    // One drawn at NOW never moves it back.
    line(NOW);
    tick();
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 13\u00a0hours 43\u00a0minutes");
  });

  it("counts the time asleep: the browser's clock moved on while no timer ran, and showing the tab puts it right", () => {
    lines("en");
    tick();
    vi.setSystemTime(new Date(Date.parse(NOW) + 3 * 60 * MIN));
    setHidden(false);
    expect(clockOf("in").textContent).toBe("in 6\u00a0days 11\u00a0hours 23\u00a0minutes");
  });
});

describe("offline (a page from this device's copy)", () => {
  it("hides the clocks, figures and words, so the banner's time is the page's time", () => {
    // The rule as globals.css writes it.
    const css = readFileSync(`${process.cwd()}/app/globals.css`, "utf8");
    const rule = /html\[data-offline\] \[data-clock\] \{[^}]*\}/.exec(css)?.[0];
    expect(rule).toContain("display: none");
    const style = document.createElement("style");
    style.textContent = rule!;
    document.head.append(style);
    twoClocks();
    withMessages(
      <p data-testid="in">
        <DeadlineLine until={UNTIL} now={NOW} labelWhenPast="Overdue" />
      </p>,
    );
    expect(getComputedStyle(clockOf("far")).display).not.toBe("none");
    document.documentElement.setAttribute("data-offline", "");
    for (const id of ["far", "near", "in"]) expect(getComputedStyle(clockOf(id)).display).toBe("none");
    // The card's words line (the business days) is not the clock: it stays.
    document.documentElement.removeAttribute("data-offline");
    style.remove();
  });
});

describe("the clock boot (root layout)", () => {
  const settle = () => new Promise<void>((resolve) => queueMicrotask(resolve));
  const block = `<script type="${CLOCK_TICKER_TYPE}" data-clock-ticker="">${CLOCK_TICKER_SCRIPT}</script>`;
  const copies = () => [...document.head.querySelectorAll("script")].map((script) => script.text);

  // Once per document, as the browser runs the layout's head script and then parses the page (a full load of a page
  // with clocks and its data block).
  let fullLoad: string[] = [];
  beforeAll(() => {
    new Function(CLOCK_BOOT_SCRIPT)();
    const parsed = document.createElement("main");
    parsed.innerHTML = `<span data-clock="open"></span>${block}`;
    document.body.append(parsed);
    expect(copies()).toEqual([]); // nothing before the document is parsed
    document.dispatchEvent(new Event("DOMContentLoaded"));
    fullLoad = copies();
    parsed.remove();
    document.head.querySelectorAll("script").forEach((script) => script.remove());
  });

  it("runs the page's ticker once the document is parsed (a full load), as a script copied from the data block", () => {
    expect(fullLoad).toEqual([CLOCK_TICKER_SCRIPT]);
  });

  it("runs the ticker when a navigation adds a clock, and only then; the first time from the page's data block", async () => {
    // Not installed yet: a navigation brings a page with clocks and its data block; the boot puts a runnable copy in
    // the head.
    const inert = document.createElement("div");
    inert.innerHTML = `<span data-clock="open"></span>${block}`;
    document.body.append(inert);
    await settle();
    expect(copies()).toEqual([CLOCK_TICKER_SCRIPT]);
    inert.remove();
    // Installed: a clock added runs the ticker; anything else does not.
    const run = vi.fn();
    page.__clocks = run;
    const other = document.createElement("p");
    other.innerHTML = "<span>no clock</span>";
    document.body.append(other);
    await settle();
    expect(run).not.toHaveBeenCalled();
    const card = document.createElement("article");
    card.innerHTML = '<span data-clock="open"></span>';
    document.body.append(card);
    await settle();
    expect(run).toHaveBeenCalledTimes(1);
    other.remove();
    card.remove();
  });

  it("runs the ticker when its data block arrives after the clocks (a page's later part, streamed in a navigation)", async () => {
    // The clocks come first, with no ticker on the page yet: nothing to run.
    const above = document.createElement("section");
    above.innerHTML = '<span data-clock="open"></span>';
    document.body.append(above);
    await settle();
    expect(copies()).toEqual([]);
    // The part below them arrives with the page's data block and no clock of its own.
    const below = document.createElement("section");
    below.innerHTML = `<p>more</p>${block}`;
    document.body.append(below);
    await settle();
    expect(copies()).toEqual([CLOCK_TICKER_SCRIPT]);
    above.remove();
    below.remove();
  });

  it("runs the ticker when a refresh draws a clock again in the same element (a new data-now or data-until)", async () => {
    const run = vi.fn();
    page.__clocks = run;
    const card = document.createElement("article");
    card.innerHTML = `<span data-clock="past" data-now="${NOW}" data-until="${at(MIN)}">Overdue</span>`;
    document.body.append(card);
    await settle();
    expect(run).toHaveBeenCalledTimes(1);
    const clock = card.querySelector("[data-clock]")!;
    clock.setAttribute("data-now", at(5 * MIN));
    await settle();
    expect(run).toHaveBeenCalledTimes(2);
    clock.setAttribute("data-until", at(20 * MIN));
    await settle();
    expect(run).toHaveBeenCalledTimes(3);
    // What the ticker writes (the state, the figures) runs nothing.
    clock.setAttribute("data-clock", "open");
    clock.innerHTML = "<time><span>x</span></time>";
    await settle();
    expect(run).toHaveBeenCalledTimes(3);
    card.remove();
  });

  it("with React: a refresh that redraws a clock turned past makes it tick again, its state and figures the server's", async () => {
    const view = (until: string, now: string) => (
      <div data-testid="card">
        <DeadlineClock until={until} now={now} labelWhenPast="Overdue" mine />
      </div>
    );
    const { rerender } = withMessages(view(at(MIN), NOW));
    tick();
    vi.advanceTimersByTime(2 * MIN);
    expect(clockOf("card").getAttribute("data-clock")).toBe("past");
    expect(vi.getTimerCount()).toBe(0);
    // router.refresh(): the question was answered, the window moved; React keeps the element, sets its new data-now,
    // data-until and inside, and leaves data-clock (its prop did not change) as the ticker wrote it.
    rerender(
      <NextIntlClientProvider locale="en" messages={en} timeZone="Africa/Nairobi">
        {view(at(12 * MIN), at(2 * MIN))}
      </NextIntlClientProvider>,
    );
    await settle();
    expect(figures("card")).toEqual(["10"]);
    expect(clockOf("card").getAttribute("data-clock")).toBe("warm");
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(MIN);
    expect(figures("card")).toEqual(["9"]);
  });
});

/** twoClocks as the server would draw them at `now`. */
function twoClocksAt(locale: "en" | "sw", now: string) {
  const past = locale === "en" ? "Overdue" : "Imechelewa";
  return withMessages(
    <main>
      <div data-testid="far">
        <DeadlineClock until={UNTIL} now={now} labelWhenPast={past} />
      </div>
      <div data-testid="near">
        <DeadlineClock until={at(2 * MIN - 1)} now={now} labelWhenPast={past} mine />
      </div>
    </main>,
    locale,
  );
}
