import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startTransition } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup, renderToString } from "react-dom/server";

import { celebrationSeenFromCookies } from "./celebration-store";
import { ClosedCelebration } from "./ClosedCelebration";

// D-52 (feel): a closed engagement is celebrated once per device, then only its chip and timeline say so.

const props = { engagementId: "e-1", title: "Closed and done", body: "Both sides finished this engagement.", dismiss: "Got it" };

beforeEach(() => {
  window.localStorage.clear();
  document.cookie = "wazo-closed=; path=/; max-age=0";
  document.documentElement.removeAttribute("data-celebration-seen");
  Object.defineProperty(navigator, "vibrate", { value: vi.fn(() => true), configurable: true });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ClosedCelebration", () => {
  it("arrives with the page exactly when the cookie says this engagement was not seen (no layout shift either way)", () => {
    const html = (initialSeen: boolean) => renderToStaticMarkup(<ClosedCelebration {...props} initialSeen={initialSeen} />);
    expect(html(false)).toContain('data-celebration="e-1"');
    expect(html(false)).toContain("Got it");
    expect(html(true)).toBe("");
    const cookies = (value?: string) => ({ get: (name: string) => (name === "wazo-closed" && value ? { value } : undefined) });
    expect(celebrationSeenFromCookies(cookies("e-7.e-1"), "e-1")).toBe(true);
    expect(celebrationSeenFromCookies(cookies("e-7.e-1"), "e-2")).toBe(false);
    expect(celebrationSeenFromCookies(cookies("e-10"), "e-1")).toBe(false); // whole ids, never a prefix
    expect(celebrationSeenFromCookies(cookies(), "e-1")).toBe(false);
  });

  it("shows once with the seal, a buzz and one button, then stays away", () => {
    const { container } = render(<ClosedCelebration {...props} />);
    expect(screen.getByRole("region", { name: "Closed and done" })).toBeTruthy();
    expect(container.querySelector("[data-seal]")).not.toBeNull();
    expect(navigator.vibrate).toHaveBeenCalledWith([12, 40, 18]);
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("region")).toBeNull();
    expect(window.localStorage.getItem("wazo-closed:v1:e-1")).toBe("seen");
    expect(document.cookie).toMatch(/(^|; )wazo-closed=(e-\d+\.)*e-1(;|$)/); // what the server reads: the card never arrives again
    cleanup();
    render(<ClosedCelebration {...props} />);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("clears the before-paint marker when it mounts, so a card another page's marker would hide is shown", () => {
    document.documentElement.setAttribute("data-celebration-seen", "e-9");
    render(<ClosedCelebration {...props} engagementId="e-10" initialSeen={false} />);
    expect(document.documentElement.hasAttribute("data-celebration-seen")).toBe(false);
    expect(screen.getByRole("region", { name: "Closed and done" })).toBeTruthy();
    cleanup();
    document.documentElement.setAttribute("data-celebration-seen", "e-9");
    window.localStorage.setItem("wazo-closed:v1:e-9", "seen");
    render(<ClosedCelebration {...props} engagementId="e-9" initialSeen={false} />);
    expect(document.documentElement.hasAttribute("data-celebration-seen")).toBe(false); // hydration has the last word
    expect(screen.queryByRole("region")).toBeNull();
  });

  /**
   * What the page could show between tasks (never under act(), which would flush everything at once): the card under
   * the marker ("hidden"), the card without it ("painted"), or no card ("gone"). React may have committed before the
   * first sample, so a test asserts what was never seen and what was, not an exact sequence. The root is mounted in
   * a transition, as Next mounts and hydrates.
   */
  const paintable = async (container: HTMLElement, mount: () => Root): Promise<string[]> => {
    const actEnvironment = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = false;
    document.body.appendChild(container);
    const states = new Set<string>();
    let root: Root | undefined;
    try {
      startTransition(() => {
        root = mount();
      });
      for (let tick = 0; tick < 40; tick += 1) {
        await new Promise((resolve) => setImmediate(resolve));
        const card = container.querySelector("[data-celebration]") !== null;
        const marker = document.documentElement.hasAttribute("data-celebration-seen");
        states.add(card ? (marker ? "hidden" : "painted") : "gone");
      }
    } finally {
      (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = actEnvironment;
      document.documentElement.removeAttribute("data-celebration-seen");
      document.cookie = "wazo-closed=; path=/; max-age=0";
      container.remove();
      root?.unmount(); // last: an unmount that throws must not skip the lines above
    }
    return [...states];
  };

  it("never paints a card storage remembers while hydrating", async () => {
    // The cookie lapsed, so the server drew the card and the head script set the marker. Next hydrates in a
    // transition, whose store check (which removes the card) runs in a later task than the layout effects: the
    // marker must outlive the card, so that between the two the page never shows it (and never shifts).
    const element = <ClosedCelebration {...props} engagementId="e-11" initialSeen={false} />;
    const container = document.createElement("div");
    container.innerHTML = renderToString(element);
    window.localStorage.setItem("wazo-closed:v1:e-11", "seen");
    document.documentElement.setAttribute("data-celebration-seen", "e-11");
    const states = await paintable(container, () => hydrateRoot(container, element));
    expect(states).not.toContain("painted");
    expect(states).toContain("gone");
  });

  it("never paints an unseen card hidden under a marker another page left", async () => {
    // A client-side navigation from a page whose marker no shell cleared (a tracker that is not closed) to an unseen
    // closed tracker: the marker must go before the card's first paint, so the card never appears late (a shift).
    const container = document.createElement("div");
    document.documentElement.setAttribute("data-celebration-seen", "e-9");
    const states = await paintable(container, () => {
      const root = createRoot(container);
      root.render(<ClosedCelebration {...props} engagementId="e-10" initialSeen={false} />);
      return root;
    });
    expect(states).not.toContain("hidden");
    expect(states).toContain("painted");
  });

  it("is remembered per engagement, in storage or in the cookie", () => {
    window.localStorage.setItem("wazo-closed:v1:e-1", "seen");
    render(<ClosedCelebration {...props} engagementId="e-2" />);
    expect(screen.getByRole("region", { name: "Closed and done" })).toBeTruthy();
    cleanup();
    document.cookie = "wazo-closed=e-5; path=/";
    render(<ClosedCelebration {...props} engagementId="e-5" />);
    expect(screen.queryByRole("region")).toBeNull();
    document.cookie = "wazo-closed=; path=/; max-age=0";
  });

  it("closes and moves focus to the page title even when storage refuses the write", () => {
    document.body.innerHTML = '<main id="main" tabindex="-1"><h1>Tracker</h1><div id="host"></div></main>';
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    render(<ClosedCelebration {...props} engagementId="e-3" />, { container: document.getElementById("host")! });
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("region")).toBeNull();
    expect(document.activeElement).toBe(document.querySelector("h1"));
    setItem.mockRestore();
    document.body.innerHTML = "";
  });

  it("does not buzz before the person has touched the page", () => {
    Object.defineProperty(navigator, "userActivation", { value: { hasBeenActive: false }, configurable: true });
    render(<ClosedCelebration {...props} engagementId="e-4" />);
    expect(navigator.vibrate).not.toHaveBeenCalled();
    Object.defineProperty(navigator, "userActivation", { value: undefined, configurable: true });
  });
});
