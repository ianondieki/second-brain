import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderToString } from "react-dom/server";

import { ClientStrings } from "@/components/ClientStrings";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { FirstLoginTour, TOUR_DWELL_MS } from "./FirstLoginTour";
import { finishTour, resetTour, tourCookie, tourDoneFromCookies, tourStorageKey, TOUR_INIT_SCRIPT } from "./tour-store";

// The first-login tour (D-52; docs/spec/07): three steps, skippable from the first, remembered in this browser.

afterEach(cleanup);
beforeEach(() => {
  window.localStorage.clear();
  resetTour("developer");
  resetTour("org");
});

describe("FirstLoginTour", () => {
  it("renders on the server exactly when the cookie says the tour was not seen (no layout shift either way)", () => {
    const html = (initialDone: boolean) =>
      renderToString(
        <ClientStrings strings={{ tour: en.tour }}>
          <FirstLoginTour side="developer" initialDone={initialDone} />
        </ClientStrings>,
      );
    expect(html(false)).toContain('role="dialog"');
    expect(html(true)).not.toContain('role="dialog"');
    expect(tourDoneFromCookies({ get: (name) => (name === tourCookie("developer") ? { value: "done" } : undefined) }, "developer")).toBe(true);
    expect(tourDoneFromCookies({ get: (name) => (name === tourCookie("developer") ? { value: "done" } : undefined) }, "org")).toBe(false);
    expect(tourDoneFromCookies({ get: () => undefined }, "developer")).toBe(false);
  });

  it("writes the cookie again when storage remembers the tour but the cookie has lapsed", () => {
    finishTour("developer");
    document.cookie = `${tourCookie("developer")}=; path=/; max-age=0`;
    expect(document.cookie).not.toContain("wazo-tour-developer=done");
    renderWithIntl(<FirstLoginTour side="developer" />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.cookie).toContain("wazo-tour-developer=done");
  });

  it("stays away when only the cookie remembers it, and the inline script hides a stale one before paint", () => {
    window.localStorage.clear();
    document.cookie = `${tourCookie("org")}=done; path=/`;
    renderWithIntl(<FirstLoginTour side="org" />);
    expect(screen.queryByRole("dialog")).toBeNull(); // the client reads the cookie too: no tour appears after hydration
    document.cookie = `${tourCookie("org")}=; path=/; max-age=0`;
    window.localStorage.setItem(tourStorageKey("developer"), "done");
    document.documentElement.removeAttribute("data-tour-seen");
    new Function(TOUR_INIT_SCRIPT)();
    expect(document.documentElement.getAttribute("data-tour-seen")).toBe("developer");
    document.documentElement.removeAttribute("data-tour-seen");
  });

  it("marks the document when a side's tour is finished and unmarks it on reset, so a client-side visit home shows it again", () => {
    document.documentElement.setAttribute("data-tour-seen", "org");
    finishTour("developer");
    expect(document.documentElement.getAttribute("data-tour-seen")).toBe("org developer");
    resetTour("developer"); // Help's "Show the tour again": the CSS hide (globals.css) must let go of this side
    expect(document.documentElement.getAttribute("data-tour-seen")).toBe("org");
    renderWithIntl(<FirstLoginTour side="developer" initialDone={false} />);
    expect(screen.getByRole("dialog", { name: "This is your home" })).toBeTruthy();
    resetTour("org");
    expect(document.documentElement.hasAttribute("data-tour-seen")).toBe(false);
  });

  it("shows the first of three steps as a non-modal dialog with Skip and Next", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const dialog = screen.getByRole("dialog", { name: "This is your home" });
    expect(dialog.getAttribute("aria-modal")).toBeNull();
    expect(dialog.textContent).toContain("Step 1 of 3");
    expect(screen.getByRole("button", { name: "Skip tour" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Next" })).toBeTruthy();
    expect(document.querySelector("[data-primary]")).toBeNull();
  });

  it("walks the steps and remembers Done", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Every idea gets a certificate" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "One tracker for both sides" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Skip tour" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.localStorage.getItem(tourStorageKey("developer"))).toBe("done");
    expect(document.cookie).toContain("wazo-tour-developer=done"); // what the server reads on the next visit
  });

  it("closes on Escape pressed inside it (not elsewhere) and hands focus to the page title", () => {
    document.body.innerHTML = '<main id="main" tabindex="-1"><h1>Home</h1><button id="menu">Account</button><div id="host"></div></main>';
    renderWithIntl(<FirstLoginTour side="developer" />, { container: document.getElementById("host")! });
    fireEvent.keyDown(document.getElementById("menu")!, { key: "Escape" }); // the account menu's Escape, not the tour's
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("button", { name: "Next" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.localStorage.getItem(tourStorageKey("developer"))).toBe("done");
    expect(document.activeElement).toBe(document.querySelector("h1"));
    document.body.innerHTML = "";
  });

  it("closes even when storage refuses the write", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    renderWithIntl(<FirstLoginTour side="developer" />);
    fireEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    setItem.mockRestore();
  });

  it("remembers Skip and stays away afterwards", () => {
    const first = renderWithIntl(<FirstLoginTour side="org" />);
    expect(screen.getByRole("dialog", { name: "Proposals arrive in your Inbox" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    first.unmount();
    renderWithIntl(<FirstLoginTour side="org" />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// P23-2: the tour as a slide show. Steps slide on a six-second cadence, hold still while the person is with it, and
// stop at the last; Back, Next, the steps' buttons, Pause, a swipe and the arrow keys move it; reduced motion
// crossfades and never advances on its own.
describe("FirstLoginTour as a slide show", () => {
  const title = () => screen.getByRole("dialog").getAttribute("data-tour");
  const tick = (ms: number) => act(() => vi.advanceTimersByTime(ms));
  const live = () => document.querySelector("[aria-live='polite']")!.textContent;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  });

  it("advances every six seconds, says so in a polite live region without moving focus, and stops at the last step", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    expect(title()).toBe("devHome");
    expect(live()).toBe("Step 1 of 3: This is your home");
    tick(TOUR_DWELL_MS - 1);
    expect(title()).toBe("devHome");
    tick(1);
    expect(title()).toBe("devIdeas");
    expect(screen.getByRole("dialog", { name: "Every idea gets a certificate" })).toBeTruthy();
    expect(live()).toBe("Step 2 of 3: Every idea gets a certificate");
    expect(document.activeElement).toBe(document.body);
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("devTracker");
    tick(TOUR_DWELL_MS * 3);
    expect(title()).toBe("devTracker"); // no loop
    expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
  });

  it("holds while hovered and resumes with the time that was left", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const dialog = screen.getByRole("dialog");
    tick(4000);
    fireEvent.pointerEnter(dialog, { pointerType: "mouse" });
    expect(dialog.hasAttribute("data-held")).toBe(true);
    tick(TOUR_DWELL_MS * 2);
    expect(title()).toBe("devHome");
    fireEvent.pointerLeave(dialog, { pointerType: "mouse" });
    expect(dialog.hasAttribute("data-held")).toBe(false);
    tick(1999);
    expect(title()).toBe("devHome");
    tick(1);
    expect(title()).toBe("devIdeas");
  });

  /** Focus the way a keyboard does: the browser matches :focus-visible (jsdom never does). */
  function keyboardFocus(element: HTMLElement) {
    const matches = vi.spyOn(element, "matches").mockImplementation((selector: string) => selector === ":focus-visible");
    element.focus();
    fireEvent.focus(element);
    matches.mockRestore();
  }

  it("holds while keyboard focus is inside it and resumes when focus leaves", () => {
    document.body.innerHTML = '<button id="outside">Outside</button><div id="host"></div>';
    renderWithIntl(<FirstLoginTour side="developer" />, { container: document.getElementById("host")! });
    const next = screen.getByRole("button", { name: "Next" });
    keyboardFocus(next);
    tick(TOUR_DWELL_MS * 2);
    expect(title()).toBe("devHome");
    fireEvent.blur(next, { relatedTarget: document.getElementById("outside") });
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("devIdeas");
    document.body.innerHTML = "";
  });

  it("keeps going after a mouse click focuses one of its buttons (focus without :focus-visible holds nothing)", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const step2 = screen.getByRole("button", { name: "Step 2" });
    step2.focus();
    fireEvent.focus(step2); // a click's focus: jsdom, like the browser after a click, does not match :focus-visible
    fireEvent.click(step2);
    expect(title()).toBe("devIdeas");
    expect(screen.getByRole("dialog").hasAttribute("data-held")).toBe(false);
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("devTracker");
  });

  it("starts a step's six seconds again when it comes back, as its progress line does", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const dialog = screen.getByRole("dialog");
    tick(4000);
    fireEvent.pointerEnter(dialog, { pointerType: "mouse" }); // held with 2 s left on the first step
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.pointerLeave(dialog, { pointerType: "mouse" });
    tick(TOUR_DWELL_MS - 1);
    expect(title()).toBe("devHome");
    tick(1);
    expect(title()).toBe("devIdeas");
  });

  it("hands focus from Pause to Done when the last step hides Pause (after Play, or an arrow key)", () => {
    const first = renderWithIntl(<FirstLoginTour side="developer" />);
    const pause = screen.getByRole("button", { name: "Pause" });
    keyboardFocus(pause);
    fireEvent.click(pause); // paused
    fireEvent.click(pause); // Play: overrides the focus hold
    tick(TOUR_DWELL_MS);
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("devTracker");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Done" }));
    first.unmount();
    resetTour("developer");
    renderWithIntl(<FirstLoginTour side="developer" />);
    fireEvent.click(screen.getByRole("button", { name: "Step 2" }));
    const pause2 = screen.getByRole("button", { name: "Pause" });
    keyboardFocus(pause2);
    fireEvent.keyDown(pause2, { key: "ArrowRight" });
    expect(title()).toBe("devTracker");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Done" }));
  });

  it("holds while a finger is on it and while the tab is hidden", () => {
    renderWithIntl(<FirstLoginTour side="org" />);
    const dialog = screen.getByRole("dialog");
    fireEvent.pointerDown(dialog, { pointerType: "touch", clientX: 100 });
    tick(TOUR_DWELL_MS * 2);
    expect(title()).toBe("orgInbox");
    fireEvent.pointerUp(dialog, { pointerType: "touch", clientX: 105 }); // a tap, not a swipe
    expect(title()).toBe("orgInbox");
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    tick(TOUR_DWELL_MS * 2);
    expect(title()).toBe("orgInbox");
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("orgNda");
  });

  it("has a visible Pause toggle that stops it, and Play that starts it again", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const pause = screen.getByRole("button", { name: "Pause" });
    expect(pause.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(pause);
    expect(pause.getAttribute("aria-pressed")).toBe("true");
    expect(pause.getAttribute("title")).toBe("Pause"); // a toggle keeps its name; the icon shows the state
    expect(pause.querySelector("svg path")!.getAttribute("d")).toMatch(/^M5 5a2/); // the play triangle
    tick(TOUR_DWELL_MS * 3);
    expect(title()).toBe("devHome");
    keyboardFocus(pause); // pressing Play from the keyboard: focus is in the panel, Play still wins
    fireEvent.click(pause);
    expect(pause.getAttribute("aria-pressed")).toBe("false");
    tick(TOUR_DWELL_MS);
    expect(title()).toBe("devIdeas");
  });

  it("moves with Back, Next and the steps' own buttons; Back is not on the first step", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
    const dots = ["Step 1", "Step 2", "Step 3"].map((name) => screen.getByRole("button", { name }));
    expect(dots[0].getAttribute("aria-current")).toBe("step");
    fireEvent.click(dots[2]);
    expect(title()).toBe("devTracker");
    expect(dots[2].getAttribute("aria-current")).toBe("step");
    expect(dots[0].hasAttribute("data-done")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(title()).toBe("devIdeas");
    expect(screen.getByRole("dialog").querySelector(".tour-slides")!.hasAttribute("data-back")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(title()).toBe("devTracker");
  });

  it("hands focus to Next when the focused Back leaves with the first step", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    const back = screen.getByRole("button", { name: "Back" });
    back.focus();
    fireEvent.click(back);
    expect(title()).toBe("devHome");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next" }));
  });

  it("moves with a sideways swipe of 40 px or more, and with the arrow keys inside it", () => {
    renderWithIntl(<FirstLoginTour side="developer" />);
    const dialog = screen.getByRole("dialog");
    fireEvent.pointerDown(dialog, { pointerType: "touch", clientX: 200 });
    fireEvent.pointerUp(dialog, { pointerType: "touch", clientX: 161 });
    expect(title()).toBe("devHome"); // 39 px: not yet
    fireEvent.pointerDown(dialog, { pointerType: "touch", clientX: 200 });
    fireEvent.pointerUp(dialog, { pointerType: "touch", clientX: 150 });
    expect(title()).toBe("devIdeas");
    fireEvent.pointerDown(dialog, { pointerType: "touch", clientX: 100 });
    fireEvent.pointerUp(dialog, { pointerType: "touch", clientX: 180 });
    expect(title()).toBe("devHome");
    fireEvent.keyDown(screen.getByRole("button", { name: "Next" }), { key: "ArrowRight" });
    expect(title()).toBe("devIdeas");
    fireEvent.keyDown(screen.getByRole("button", { name: "Next" }), { key: "ArrowLeft" });
    expect(title()).toBe("devHome");
  });

  it("under reduced motion crossfades, never advances on its own and has no Pause", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    renderWithIntl(<FirstLoginTour side="developer" />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.classList.contains("tour-fade")).toBe(true);
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    tick(TOUR_DWELL_MS * 3);
    expect(title()).toBe("devHome");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(title()).toBe("devIdeas");
  });

  it("shows only the current step to assistive technology, with the scene it is given", () => {
    renderWithIntl(<FirstLoginTour side="developer" scenes={[<i key="a" data-scene="a" />, <i key="b" data-scene="b" />, <i key="c" data-scene="c" />]} />);
    const slides = [...screen.getByRole("dialog").querySelectorAll<HTMLElement>(".tour-slide")];
    expect(slides.map((slide) => slide.getAttribute("aria-hidden"))).toEqual([null, "true", "true"]);
    expect(slides.map((slide) => slide.hasAttribute("inert"))).toEqual([false, true, true]);
    expect(slides[0].querySelector("[data-scene='a']")).not.toBeNull();
    expect(within(slides[0]).getByRole("heading", { name: "This is your home" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(slides.map((slide) => slide.getAttribute("data-slide"))).toEqual(["out", "in", null]);
  });
});
