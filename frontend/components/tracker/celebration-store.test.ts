import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CELEBRATION_INIT_SCRIPT,
  celebrationCookieSet,
  celebrationIdsOf,
  celebrationSeen,
  clearCelebrationMarker,
  COOKIE_LIMIT,
  rememberCelebrationCookie,
} from "./celebration-store";

// The celebration's memory (D-52, feel): one small cookie for the server, storage for good, a before-paint hide.

const clearCookie = () => {
  document.cookie = "wazo-closed=; path=/; max-age=0";
};

beforeEach(() => {
  window.localStorage.clear();
  clearCookie();
  clearCelebrationMarker();
});
afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("the celebration cookie", () => {
  it("lists the last engagements in one cookie, most recent last, and lets the oldest go beyond the limit", () => {
    for (let n = 1; n <= COOKIE_LIMIT + 2; n += 1) rememberCelebrationCookie(`e-${n}`);
    const ids = celebrationIdsOf(document.cookie.split("; ").find((c) => c.startsWith("wazo-closed="))?.slice("wazo-closed=".length));
    expect(ids).toHaveLength(COOKIE_LIMIT);
    expect(ids[0]).toBe("e-3");
    expect(ids[COOKIE_LIMIT - 1]).toBe(`e-${COOKIE_LIMIT + 2}`);
    expect(celebrationCookieSet("e-1")).toBe(false);
    expect(celebrationCookieSet("e-3")).toBe(true);
    rememberCelebrationCookie("e-3"); // seen again: moves to the most recent place, no duplicate
    expect(celebrationIdsOf(document.cookie.slice("wazo-closed=".length)).filter((id) => id === "e-3")).toHaveLength(1);
    expect(document.cookie).toMatch(/e-3$/);
    expect(document.cookie.length).toBeLessThan(400);
  });

  it("carries only ids a cookie can hold", () => {
    rememberCelebrationCookie("e;1");
    expect(document.cookie).toBe("");
    rememberCelebrationCookie("0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f");
    expect(celebrationCookieSet("0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f")).toBe(true);
  });

  it("falls through to the cookie when storage cannot be read, as the server did", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(celebrationSeen("e-1")).toBe(false); // the server drew the card: the client keeps it
    document.cookie = "wazo-closed=e-1; path=/";
    expect(celebrationSeen("e-1")).toBe(true); // the server withheld it: the client draws nothing
  });
});

describe("the before-paint hide", () => {
  it("marks the document on a tracker whose celebration only storage remembers, and the shell clears the mark", () => {
    window.localStorage.setItem("wazo-closed:v1:e-9", "seen");
    window.history.replaceState({}, "", "/dev/engagements/e-9?tab=files");
    new Function(CELEBRATION_INIT_SCRIPT)();
    expect(document.documentElement.getAttribute("data-celebration-seen")).toBe("e-9");
    clearCelebrationMarker();
    expect(document.documentElement.hasAttribute("data-celebration-seen")).toBe(false);
    window.history.replaceState({}, "", "/org/engagements/e-8");
    new Function(CELEBRATION_INIT_SCRIPT)();
    expect(document.documentElement.hasAttribute("data-celebration-seen")).toBe(false); // e-8 was never seen
    window.history.replaceState({}, "", "/dev/ideas/e-9");
    new Function(CELEBRATION_INIT_SCRIPT)();
    expect(document.documentElement.hasAttribute("data-celebration-seen")).toBe(false); // not a tracker
  });
});
