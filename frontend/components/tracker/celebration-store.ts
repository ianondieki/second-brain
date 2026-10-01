// The closed-engagement celebration's memory (D-52, feel): "seen" per engagement in this browser, in storage (what
// the client reads) and in a cookie (what the server reads, so the tracker arrives with or without the card and
// nothing shifts). No React in this module: the server component reads it too.

const KEY_PREFIX = "wazo-closed:v1:";
const COOKIE_PREFIX = "wazo-closed-";
const COOKIE_YEAR = 60 * 60 * 24 * 365;
const listeners = new Set<() => void>();
/** Dismissed on this page: the card closes even when storage refuses the write (a full quota, a private window). */
const dismissed = new Set<string>();

export function celebrationKey(id: string): string {
  return KEY_PREFIX + id;
}

export function celebrationCookie(id: string): string {
  return COOKIE_PREFIX + id;
}

/** What the server reads (next/headers cookies()): true when this browser already saw this engagement's celebration. */
export function celebrationSeenFromCookies(store: { get(name: string): { value: string } | undefined }, id: string): boolean {
  return store.get(celebrationCookie(id))?.value === "seen";
}

export function celebrationCookieSet(id: string): boolean {
  return document.cookie.split("; ").includes(`${celebrationCookie(id)}=seen`);
}

export function rememberCelebrationCookie(id: string): void {
  document.cookie = `${celebrationCookie(id)}=seen; path=/; max-age=${COOKIE_YEAR}; SameSite=Lax`;
}

/** True once seen: in memory, in storage, or in the cookie; storage off counts as seen (never celebrate twice by accident). */
export function celebrationSeen(id: string): boolean {
  if (dismissed.has(id)) return true;
  try {
    if (window.localStorage.getItem(celebrationKey(id)) === "seen") return true;
  } catch {
    return true;
  }
  return celebrationCookieSet(id);
}

/** Marks the celebration as seen for this engagement; it never shows again on this device (or, without storage, on this page). */
export function dismissCelebration(id: string): void {
  dismissed.add(id);
  try {
    window.localStorage.setItem(celebrationKey(id), "seen");
  } catch {
    // Storage refused the write: the in-memory mark and the cookie close the card for this page and the next visit.
  }
  rememberCelebrationCookie(id);
  for (const listener of listeners) listener();
}

export function subscribeCelebration(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}
