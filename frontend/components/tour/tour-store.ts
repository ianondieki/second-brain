// The first-login tour's memory (D-52): "done" in this browser once it was skipped or finished. A module store read
// through useSyncExternalStore, so the tour never renders on the server (its server snapshot is "done") and never
// flashes before hydration.

export const TOUR_STORAGE_KEY = "wazo-tour:v1";

const listeners = new Set<() => void>();
/** Finished on this page: the tour closes even when storage refuses the write (a full quota, a private window). */
let finishedHere = false;

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
  if (finishedHere) return true;
  try {
    return window.localStorage.getItem(TOUR_STORAGE_KEY) === "done";
  } catch {
    return true;
  }
}

export function finishTour() {
  finishedHere = true;
  try {
    window.localStorage.setItem(TOUR_STORAGE_KEY, "done");
  } catch {
    // Storage refused the write: the in-memory mark closes the tour for this page; it may show again next time.
  }
  for (const listener of listeners) listener();
}

/** Help's "Show the tour again" (components/tour/ShowTourAgain.tsx): the tour shows on the next home visit. */
export function resetTour() {
  finishedHere = false;
  try {
    window.localStorage.removeItem(TOUR_STORAGE_KEY);
  } catch {
    // Nothing to forget.
  }
  for (const listener of listeners) listener();
}
