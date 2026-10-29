// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { applyTheme, readTheme, THEME_INIT_SCRIPT, THEME_STORAGE_KEY } from "./theme";

// Dark mode (D-52): a remembered choice is applied to <html> before paint; "system" leaves the attribute off so
// app/globals.css follows prefers-color-scheme; unreadable storage never breaks the page.

function storage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

describe("theme", () => {
  it("reads a remembered choice and falls back to system", () => {
    expect(readTheme(storage({ [THEME_STORAGE_KEY]: "dark" }))).toBe("dark");
    expect(readTheme(storage({ [THEME_STORAGE_KEY]: "purple" }))).toBe("system");
    expect(readTheme(null)).toBe("system");
    expect(readTheme({ getItem: () => { throw new Error("blocked"); } })).toBe("system");
  });

  it("applies a choice to the document and remembers it; system clears both", () => {
    const root = document.createElement("html");
    const store = storage();
    applyTheme("dark", root, store);
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(store.data.get(THEME_STORAGE_KEY)).toBe("dark");
    applyTheme("system", root, store);
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(store.data.has(THEME_STORAGE_KEY)).toBe(false);
  });

  it("keeps the choice on the page when storage refuses to write", () => {
    const root = document.createElement("html");
    applyTheme("light", root, { setItem: () => { throw new Error("private"); }, removeItem: () => {} });
    expect(root.getAttribute("data-theme")).toBe("light");
  });

  it("ships an inline script that applies only light or dark, and swallows a storage error", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.setItem(THEME_STORAGE_KEY, "system");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(THEME_INIT_SCRIPT).not.toContain("\n");
  });
});
