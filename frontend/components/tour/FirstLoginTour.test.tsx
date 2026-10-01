import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderToString } from "react-dom/server";

import { ClientStrings } from "@/components/ClientStrings";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { FirstLoginTour } from "./FirstLoginTour";
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
