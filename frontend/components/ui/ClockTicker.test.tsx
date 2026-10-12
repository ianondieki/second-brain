import { cleanup, render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { gzipSync } from "node:zlib";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import { ClockFigures } from "./ClockFigures";
import { CLOCK_BOOT_SCRIPT, CLOCK_TICKER_SCRIPT, ClockTicker } from "./ClockTicker";
import { DeadlineClock, DeadlineLine } from "./DeadlineClock";

// P27 (REQ-TRACK-03, REQ-UX-05): the page's clock ticker. The server draws every clock whole; one inline script for the
// page (no React, constant text, at most 1.5 KB gzipped) moves them all on the minute boundary from the app clock, with
// the screen-reader words, the <time>'s duration and the warm and past states; it pauses while the tab is hidden and
// runs again when it is shown, restored or focused. The root layout's boot runs it for clocks a navigation adds.

const MIN = 60_000;
const NOW = "2026-10-10T06:36:00.000Z";
/** The end of 16 Oct 2026 in Nairobi: 6 d 14 h 23 m (and a fraction of a second) after NOW. */
const UNTIL = "2026-10-16T20:59:59.999Z";
const at = (ms: number) => new Date(Date.parse(NOW) + ms).toISOString();

type Page = { __appGap?: number; __clocks?: () => void };
const page = window as unknown as Page;

/** The page's ticker, run as the browser runs the inline script when it parses it. */
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
  delete page.__appGap;
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
  it("is one small constant script, no React, rendered by the page as an inert <script>", () => {
    expect(gzipSync(CLOCK_TICKER_SCRIPT).length).toBeLessThanOrEqual(1_500);
    // No English (or any language) in it: the words come from the clocks' own attributes and from Intl.
    for (const word of ["Overdue", "Imechelewa", " min", "siku", "dak ", "in {time}", "baada", "EAT"]) {
      expect(CLOCK_TICKER_SCRIPT).not.toContain(word);
    }
    expect(CLOCK_TICKER_SCRIPT).not.toMatch(/<\/script/i);
    twoClocks();
    const scripts = document.querySelectorAll("script[data-clock-ticker]");
    expect(scripts).toHaveLength(1);
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
      delete page.__appGap;
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
    expect(clockOf("line").textContent).toBe("in 6 days 14 hours 23 minutes");
    tick();
    vi.advanceTimersByTime(MIN);
    expect(clockOf("line").textContent).toBe("in 6 days 14 hours 22 minutes");
    expect(duration("line")).toBe("P6DT14H22M");
    expect(clockOf("line").querySelector("time")?.getAttribute("title")).toBe("16 Oct 2026, 23:59 EAT");
    cleanup();
    withMessages(
      <p data-testid="line">
        <DeadlineLine until={at(MIN)} now={NOW} labelWhenPast="Imechelewa" />
      </p>,
      "sw",
    );
    expect(clockOf("line").textContent).toBe("baada ya dakika 1");
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

describe("the clock boot (root layout)", () => {
  // Once per document, as the browser runs the layout's head script and then parses the page.
  beforeAll(() => {
    new Function(CLOCK_BOOT_SCRIPT)();
    document.dispatchEvent(new Event("DOMContentLoaded"));
  });

  it("runs the ticker when a navigation adds a clock, and only then; the first time from the page's inert copy", async () => {
    const settle = () => new Promise<void>((resolve) => queueMicrotask(resolve));
    // Not installed yet: a navigation brings a page with clocks and React's copy of the script, which the browser never
    // runs; the boot puts a runnable copy in the head.
    const inert = document.createElement("div");
    inert.innerHTML = `<span data-clock="open"></span><script data-clock-ticker="">${CLOCK_TICKER_SCRIPT}</script>`;
    document.body.append(inert);
    await settle();
    const copies = [...document.head.querySelectorAll("script")];
    expect(copies).toHaveLength(1);
    expect(copies[0].text).toBe(CLOCK_TICKER_SCRIPT);
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

  it("runs the ticker when its script arrives after the clocks (a page's later part, streamed in a navigation)", async () => {
    const settle = () => new Promise<void>((resolve) => queueMicrotask(resolve));
    // The clocks come first, with no ticker on the page yet: nothing to run.
    const above = document.createElement("section");
    above.innerHTML = '<span data-clock="open"></span>';
    document.body.append(above);
    await settle();
    expect(document.head.querySelectorAll("script")).toHaveLength(0);
    // The part below them arrives with the page's (inert) ticker and no clock of its own.
    const below = document.createElement("section");
    below.innerHTML = `<p>more</p><script data-clock-ticker="">${CLOCK_TICKER_SCRIPT}</script>`;
    document.body.append(below);
    await settle();
    expect([...document.head.querySelectorAll("script")].map((script) => script.text)).toEqual([CLOCK_TICKER_SCRIPT]);
    above.remove();
    below.remove();
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
