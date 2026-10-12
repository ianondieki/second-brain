// The arithmetic the deadline clocks share (P23-3, P26): plain functions and constants, no directive, so the server
// components (ClockFigures, DeadlineClock) and the client hook (useAppClock.ts) import the same values. The page's
// ticker (ClockTicker.tsx) repeats it in its inline script.

export const MINUTE = 60_000;
export const DAY = 1_440 * MINUTE;

/** Whole days, hours and minutes in a span of milliseconds (floored to the minute). */
export function splitLeft(left: number): { d: number; h: number; m: number } {
  const total = Math.floor(left / MINUTE);
  return {
    d: Math.floor(total / 1_440),
    h: Math.floor(total / 60) % 24,
    m: total % 60,
  };
}
