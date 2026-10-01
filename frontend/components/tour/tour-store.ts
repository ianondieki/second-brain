// The first-login tour's memory (D-52): "done" in this browser once it was skipped or finished, in localStorage (what
// the client reads) and in a cookie (what the server reads, so a first visit renders the tour in place with no layout
// shift and a later visit renders nothing: no flash either way). A module store read through useSyncExternalStore.

export const TOUR_STORAGE_KEY = "wazo-tour:v1";
export const TOUR_COOKIE = "wazo-tour";
const COOKIE_YEAR = 60 * 60 * 24 * 365;

/** What the server reads (next/headers cookies()): true when this browser finished or skipped the tour. */
export function tourDoneFromCookies(store: { get(name: string): { value: string } | undefined }): boolean {
  return store.get(TOUR_COOKIE)?.value === "done";
}

/** Writes the cookie the server reads; also called again on a visit where storage knows but the cookie has lapsed. */
export function rememberTourCookie(): void {
  document.cookie = `${TOUR_COOKIE}=done; path=/; max-age=${COOKIE_YEAR}; SameSite=Lax`;
}

export function tourCookieSet(): boolean {
  return document.cookie.split("; ").includes(`${TOUR_COOKIE}=done`);
}

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
  rememberTourCookie();
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
  document.cookie = `${TOUR_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
  for (const listener of listeners) listener();
}
