import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { FirstLoginTour } from "./FirstLoginTour";
import { resetTour, TOUR_STORAGE_KEY } from "./tour-store";

// The first-login tour (D-52; docs/spec/07): three steps, skippable from the first, remembered in this browser.

afterEach(cleanup);
beforeEach(() => {
  window.localStorage.clear();
  resetTour();
});

describe("FirstLoginTour", () => {
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
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe("done");
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
