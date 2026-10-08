// The writing half of the palette's Recent group (D-67, P25), kept apart and small because the top bar's Search button
// carries it on every signed-in page (the palette itself reads and checks the list: recent.ts).

export const RECENT_KEY = "wazo-recent:v1";
export const RECENT_MAX = 5;

/** The detail pages worth returning to: an idea, an engagement, a proposal sent to the organisation, a problem or
 *  Brief, a company, a team, an event. Not editors, not new-item forms, not lists. */
export const DETAIL =
  /^\/(?:dev\/(?:ideas|engagements|companies|teams)|org\/(?:engagements|inbox|problems|events)|problems)\/(?!(?:new|edit|shortlist|matches|scouts)$)[\w-]+$/;

/** Remembers a detail page at the front of this browser's list (an earlier visit moves up), keeping five. */
export function rememberVisit(
  href: string,
  title: string,
  storage: Pick<Storage, "getItem" | "setItem"> | null | undefined = globalThis.localStorage,
): void {
  const text = title.replace(/\s+/g, " ").trim().slice(0, 140);
  if (!text || !DETAIL.test(href.split("?")[0])) return;
  try {
    const list: unknown = JSON.parse(storage?.getItem(RECENT_KEY) || "[]");
    const kept = Array.isArray(list) ? list.filter((entry: { href?: unknown } | null) => entry?.href !== href) : [];
    storage?.setItem(RECENT_KEY, JSON.stringify([{ href, title: text }, ...kept].slice(0, RECENT_MAX)));
  } catch {
    // Full or blocked storage: the palette simply has no recent pages.
  }
}
