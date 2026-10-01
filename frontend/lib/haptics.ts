/**
 * Haptics (D-52, feel): a short vibration on phones that support it, for moments that deserve one (a payment
 * confirmed, an idea published, the NDA accepted, an engagement closed). Nothing happens on devices without the
 * Vibration API, and nothing happens for people who asked for reduced motion: the words and the colour carry the
 * meaning, the buzz is only a confirmation under the thumb.
 */

export type HapticKind = "tap" | "success" | "warn";

const PATTERNS: Record<HapticKind, number | number[]> = {
  tap: 10,
  success: [12, 40, 18],
  warn: 35,
};

/** True when the device can vibrate and the person has not asked for reduced motion. */
export function hapticsAvailable(): boolean {
  if (typeof navigator === "undefined" || typeof navigator.vibrate !== "function") return false;
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  }
  return true;
}

/** True once the person has tapped or typed on this page: browsers refuse a vibration before that (and log an error). */
function activated(): boolean {
  const activation = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation;
  return activation === undefined || activation.hasBeenActive;
}

/** Plays one pattern; returns whether the device accepted it. Never throws, and never asks before a gesture. */
export function haptic(kind: HapticKind): boolean {
  if (!hapticsAvailable() || !activated()) return false;
  try {
    return navigator.vibrate(PATTERNS[kind]) === true;
  } catch {
    return false;
  }
}
