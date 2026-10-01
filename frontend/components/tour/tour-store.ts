// The first-login tour's memory (D-52): "done" in this browser once it was skipped or finished. A module store read
// through useSyncExternalStore, so the tour never renders on the server (its server snapshot is "done") and never
// flashes before hydration.

export const TOUR_STORAGE_KEY = "wazo-tour:v1";

const listeners = new Set<() => void>();

export function subscribeTour(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** True when the tour was skipped or finished in this browser (or storage cannot be read: then it stays out of the way). */
export function tourDone(): boolean {
  try {
    return window.localStorage.getItem(TOUR_STORAGE_KEY) === "done";
  } catch {
    return true;
  }
}

export function finishTour() {
  try {
    window.localStorage.setItem(TOUR_STORAGE_KEY, "done");
  } catch {
    // Blocked storage: the tour closes for this page and may show again next time.
  }
  for (const listener of listeners) listener();
}

/** Help's "Show the tour again". */
export function resetTour() {
  try {
    window.localStorage.removeItem(TOUR_STORAGE_KEY);
  } catch {
    // Nothing to forget.
  }
  for (const listener of listeners) listener();
}
