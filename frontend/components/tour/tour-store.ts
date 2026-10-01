// The first-login tour's memory (D-52): "done" per side in this browser once it was skipped or finished, in
// localStorage and in a cookie. The server reads the cookie (so a first visit renders the tour in place and a later
// visit renders nothing: no layout shift), the client reads both (so the two never disagree on what to show), and
// app/layout.tsx's inline script hides a server-rendered tour before paint when only storage remembers it. A module
// store read through useSyncExternalStore.

export type TourSide = "developer" | "org";

export const TOUR_SIDES: readonly TourSide[] = ["developer", "org"];
const STORAGE_PREFIX = "wazo-tour:v1:";
const COOKIE_PREFIX = "wazo-tour-";
const COOKIE_YEAR = 60 * 60 * 24 * 365;

export function tourStorageKey(side: TourSide): string {
  return STORAGE_PREFIX + side;
}

export function tourCookie(side: TourSide): string {
  return COOKIE_PREFIX + side;
}

const listeners = new Set<() => void>();
/** Finished on this page: the tour closes even when storage refuses the write (a full quota, a private window). */
const finishedHere = new Set<TourSide>();

export function subscribeTour(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** What the server reads (next/headers cookies()): true when this browser finished or skipped this side's tour. */
export function tourDoneFromCookies(store: { get(name: string): { value: string } | undefined }, side: TourSide): boolean {
  return store.get(tourCookie(side))?.value === "done";
}

export function tourCookieSet(side: TourSide): boolean {
  return document.cookie.split("; ").includes(`${tourCookie(side)}=done`);
}

/** Writes the cookie the server reads; also called again on a visit where storage knows but the cookie has lapsed. */
export function rememberTourCookie(side: TourSide): void {
  document.cookie = `${tourCookie(side)}=done; path=/; max-age=${COOKIE_YEAR}; SameSite=Lax`;
}

/** True when this side's tour was skipped or finished in this browser (storage or cookie); storage that cannot be read counts as done. */
export function tourDone(side: TourSide): boolean {
  if (finishedHere.has(side)) return true;
  try {
    if (window.localStorage.getItem(tourStorageKey(side)) === "done") return true;
  } catch {
    return true;
  }
  return tourCookieSet(side);
}

export function finishTour(side: TourSide) {
  finishedHere.add(side);
  try {
    window.localStorage.setItem(tourStorageKey(side), "done");
  } catch {
    // Storage refused the write: the in-memory mark and the cookie close the tour for this page and the next visit.
  }
  rememberTourCookie(side);
  for (const listener of listeners) listener();
}

/** Help's "Show the tour again" (components/tour/ShowTourAgain.tsx): the tour shows on the next home visit. */
export function resetTour(side: TourSide) {
  finishedHere.delete(side);
  try {
    window.localStorage.removeItem(tourStorageKey(side));
  } catch {
    // Nothing to forget.
  }
  document.cookie = `${tourCookie(side)}=; path=/; max-age=0; SameSite=Lax`;
  for (const listener of listeners) listener();
}

/**
 * Inline in the document head, before paint (app/layout.tsx): when storage remembers a side's tour but the server
 * rendered it (the cookie had lapsed), the tour is hidden before it is ever painted (globals.css,
 * `html[data-tour-seen]`), and hydration removes it with nothing to shift.
 */
export const TOUR_INIT_SCRIPT =
  `(function(){try{var s=[];` +
  TOUR_SIDES.map((side) => `if(localStorage.getItem(${JSON.stringify(tourStorageKey(side))})==="done")s.push(${JSON.stringify(side)});`).join("") +
  `if(s.length)document.documentElement.setAttribute("data-tour-seen",s.join(" "));}catch(e){}})();`;
