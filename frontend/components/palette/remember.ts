// The writing half of the palette's Recent group (D-67, P25), kept apart and small because the top bar's Search button
// carries it on every signed-in page (the palette itself reads and checks the list: recent.ts). The list is kept per
// account under a key that holds a hash of the account's id (never the id), and only the address and the title that
// were already on screen. Any other account's list (and the unkeyed first version) is removed as soon as someone
// else is signed in, and every list on sign-out: a shared machine never shows one person's titles to the next.

const PREFIX = "wazo-recent:";
export const RECENT_MAX = 5;

/** The storage key of an account's list, from the hash the server computed. */
export function recentKey(hash: string): string {
  return `${PREFIX}v2:${hash}`;
}

/** The detail pages worth returning to: an idea, an engagement, a proposal sent to the organisation, a problem or
 *  Brief, a company, a team, an event. Not editors, not new-item forms, not lists. */
export const DETAIL =
  /^\/(?:dev\/(?:ideas|engagements|companies|teams)|org\/(?:engagements|inbox|problems|events)|problems)\/(?!(?:new|edit|shortlist|matches|scouts)$)[\w-]+$/;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

/** Removes every account's list but `keep` (every list without it: sign-out). Blocked storage is left alone. */
export function forgetRecent(keep?: string | null, storage: Store | null | undefined = globalThis.localStorage): void {
  try {
    if (!storage) return;
    const keys: string[] = [];
    for (let i = 0; i < storage.length; i += 1) {
      const name = storage.key(i);
      if (name?.startsWith(PREFIX) && name !== keep) keys.push(name);
    }
    for (const name of keys) storage.removeItem(name);
  } catch {
    // Blocked storage holds nothing to clear.
  }
}

/** Remembers a detail page at the front of the account's list (an earlier visit moves up), keeping five. */
export function rememberVisit(key: string, href: string, title: string, storage: Store | null | undefined = globalThis.localStorage): void {
  const text = title.replace(/\s+/g, " ").trim().slice(0, 140);
  if (!text || !DETAIL.test(href.split("?")[0])) return;
  try {
    const list: unknown = JSON.parse(storage?.getItem(key) || "[]");
    const kept = Array.isArray(list) ? list.filter((entry: { href?: unknown } | null) => entry?.href !== href) : [];
    storage?.setItem(key, JSON.stringify([{ href, title: text }, ...kept].slice(0, RECENT_MAX)));
  } catch {
    // Full or blocked storage: the palette simply has no recent pages.
  }
}
