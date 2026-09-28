import { flushSync } from "react-dom";

/**
 * Applies a state change at once, then moves focus to what it shows. Focus also scrolls the element into view, so
 * a screen reader reads the notice and a sighted person who pressed a button far below it (at 360 px, often more
 * than a screen away) sees what changed.
 *
 * Most calls come after an await (an API answer), outside React's event batching, where the new state may be
 * committed only after the next animation frame (seen in Chrome at 1440 px): flushSync commits it first, so the
 * element exists when `target` is read. Every state change the new screen depends on belongs in `update`, or it may
 * arrive a frame later.
 */
export function reveal(update: () => void, target: () => HTMLElement | null | undefined) {
  flushSync(update);
  target()?.focus();
}
