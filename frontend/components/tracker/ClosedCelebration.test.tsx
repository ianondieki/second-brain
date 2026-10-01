import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClosedCelebration } from "./ClosedCelebration";

// D-52 (feel): a closed engagement is celebrated once per device, then only its chip and timeline say so.

const props = { engagementId: "e-1", title: "Closed and done", body: "Both sides finished this engagement.", dismiss: "Got it" };

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(navigator, "vibrate", { value: vi.fn(() => true), configurable: true });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ClosedCelebration", () => {
  it("shows once with the seal, a buzz and one button, then stays away", () => {
    const { container } = render(<ClosedCelebration {...props} />);
    expect(screen.getByRole("region", { name: "Closed and done" })).toBeTruthy();
    expect(container.querySelector("[data-seal]")).not.toBeNull();
    expect(navigator.vibrate).toHaveBeenCalledWith([12, 40, 18]);
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("region")).toBeNull();
    expect(window.localStorage.getItem("wazo-closed:v1:e-1")).toBe("seen");
    cleanup();
    render(<ClosedCelebration {...props} />);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("is remembered per engagement", () => {
    window.localStorage.setItem("wazo-closed:v1:e-1", "seen");
    render(<ClosedCelebration {...props} engagementId="e-2" />);
    expect(screen.getByRole("region", { name: "Closed and done" })).toBeTruthy();
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
