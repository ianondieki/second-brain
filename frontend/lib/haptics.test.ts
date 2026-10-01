import { afterEach, describe, expect, it, vi } from "vitest";

import { haptic, hapticsAvailable } from "./haptics";

// D-52 (feel): a confirmation under the thumb only where the device can give one and motion is not reduced.

function withMedia(reduced: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduced && query.includes("reduce") }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "vibrate", { value: undefined, configurable: true });
});

describe("haptic", () => {
  it("plays the success pattern when the device can vibrate", () => {
    const vibrate = vi.fn(() => true);
    Object.defineProperty(navigator, "vibrate", { value: vibrate, configurable: true });
    withMedia(false);
    expect(hapticsAvailable()).toBe(true);
    expect(haptic("success")).toBe(true);
    expect(vibrate).toHaveBeenCalledWith([12, 40, 18]);
  });

  it("stays silent without the Vibration API", () => {
    withMedia(false);
    expect(hapticsAvailable()).toBe(false);
    expect(haptic("tap")).toBe(false);
  });

  it("stays silent under reduced motion", () => {
    const vibrate = vi.fn(() => true);
    Object.defineProperty(navigator, "vibrate", { value: vibrate, configurable: true });
    withMedia(true);
    expect(haptic("warn")).toBe(false);
    expect(vibrate).not.toHaveBeenCalled();
  });

  it("never throws when the browser refuses", () => {
    Object.defineProperty(navigator, "vibrate", {
      value: () => {
        throw new Error("not allowed");
      },
      configurable: true,
    });
    withMedia(false);
    expect(haptic("tap")).toBe(false);
  });
});
