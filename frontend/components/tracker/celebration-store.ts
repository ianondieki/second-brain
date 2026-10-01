// The closed-engagement celebration's memory (D-52, feel): "seen" per engagement in this browser, in storage (what
// the client reads, for good) and in one cookie (what the server reads, so the tracker arrives with or without the
// card and nothing shifts). The cookie keeps only the last few engagements, so it stays small on every request;
// an older one the cookie has let go is still hidden before paint by CELEBRATION_INIT_SCRIPT, from storage. No React
// in this module: the server component reads it too.

const KEY_PREFIX = "wazo-closed:v1:";
export const CELEBRATION_COOKIE = "wazo-closed";
/** How many engagements the cookie remembers (about 37 bytes each): enough for the trackers a device reopens. */
export const COOKIE_LIMIT = 8;
const COOKIE_YEAR = 60 * 60 * 24 * 365;
const SEPARATOR = ".";
/** The engagement ids the cookie can carry (UUIDs and the fixtures' short ids); anything else stays in storage only. */
const COOKIE_SAFE_ID = /^[\w-]+$/;
const SEEN_ATTRIBUTE = "data-celebration-seen";
/** The tracker routes (app/(app)/{dev,org}/engagements/[id]), as the before-paint script reads them. */
const TRACKER_PATH = "^\\/(?:dev|org)\\/engagements\\/([^\\/?#]+)";
const listeners = new Set<() => void>();
/** Dismissed on this page: the card closes even when storage refuses the write (a full quota, a private window). */
const dismissed = new Set<string>();

export function celebrationKey(id: string): string {
  return KEY_PREFIX + id;
}

/** The ids a cookie value lists, most recent last. */
export function celebrationIdsOf(value: string | undefined): string[] {
  return value ? value.split(SEPARATOR).filter((id) => id !== "") : [];
}

/** What the server reads (next/headers cookies()): true when this browser already saw this engagement's celebration. */
export function celebrationSeenFromCookies(store: { get(name: string): { value: string } | undefined }, id: string): boolean {
  return celebrationIdsOf(store.get(CELEBRATION_COOKIE)?.value).includes(id);
}

function cookieValue(): string | undefined {
  const prefix = `${CELEBRATION_COOKIE}=`;
  return document.cookie
    .split("; ")
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

export function celebrationCookieSet(id: string): boolean {
  return celebrationIdsOf(cookieValue()).includes(id);
}

/** Adds this engagement to the cookie (most recent last) and lets the oldest go beyond COOKIE_LIMIT. */
export function rememberCelebrationCookie(id: string): void {
  if (!COOKIE_SAFE_ID.test(id)) return;
  const ids = celebrationIdsOf(cookieValue()).filter((seen) => seen !== id);
  ids.push(id);
  const value = ids.slice(-COOKIE_LIMIT).join(SEPARATOR);
  document.cookie = `${CELEBRATION_COOKIE}=${value}; path=/; max-age=${COOKIE_YEAR}; SameSite=Lax`;
}

/**
 * True once seen: in memory, in storage, or in the cookie. Storage that cannot be read falls through to the cookie,
 * the server's own answer, so the client never removes a card the server drew (a shift) nor draws one it withheld.
 */
export function celebrationSeen(id: string): boolean {
  if (dismissed.has(id)) return true;
  try {
    if (window.localStorage.getItem(celebrationKey(id)) === "seen") return true;
  } catch {
    // Storage is off: the cookie decides, as it did on the server.
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

/** Hydration has the last word (CelebrationShell): the before-paint marker goes once React draws or withholds the card. */
export function clearCelebrationMarker(): void {
  document.documentElement.removeAttribute(SEEN_ATTRIBUTE);
}

/**
 * Inline in the document head, before paint (app/layout.tsx): on a tracker whose celebration storage remembers but
 * the cookie has let go (it keeps only the last COOKIE_LIMIT, and a cookie set from a page may lapse sooner than
 * storage), the server-drawn card is hidden before it is ever painted (globals.css, `html[data-celebration-seen]`),
 * and hydration removes it with nothing to shift.
 */
export const CELEBRATION_INIT_SCRIPT =
  `(function(){try{var m=new RegExp(${JSON.stringify(TRACKER_PATH)}).exec(location.pathname);` +
  `if(m&&localStorage.getItem(${JSON.stringify(KEY_PREFIX)}+m[1])==="seen")` +
  `document.documentElement.setAttribute(${JSON.stringify(SEEN_ATTRIBUTE)},m[1]);}catch(e){}})();`;
