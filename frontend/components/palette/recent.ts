import { DETAIL, RECENT_KEY, RECENT_MAX, rememberVisit } from "./remember";
import type { PaletteLink } from "./types";

// The command palette's "Recent" group (D-67, P25): the last five detail pages this browser opened, by their address
// and the title already on their screen. Kept in this browser only (localStorage), nothing else about the page;
// storage that is full, blocked or holding something unreadable is ignored. Written by the Search button
// (remember.ts), read and checked here by the palette.

export { RECENT_KEY, RECENT_MAX };

export function isDetailPath(pathname: string): boolean {
  return DETAIL.test(pathname);
}

function valid(entry: unknown): entry is PaletteLink {
  if (!entry || typeof entry !== "object") return false;
  const { href, title } = entry as Record<string, unknown>;
  return typeof href === "string" && href.startsWith("/") && !href.startsWith("//") && typeof title === "string" && title.length > 0;
}

/** The remembered pages, newest first. */
export function readRecent(storage: Pick<Storage, "getItem"> | null | undefined = globalThis.localStorage): PaletteLink[] {
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(RECENT_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(valid)
      .slice(0, RECENT_MAX)
      .map(({ href, title }) => ({ id: `recent-${href}`, title, href }));
  } catch {
    return [];
  }
}

/** Remembers a page at the front (once: an earlier visit to the same address moves up), keeping five. */
export function rememberPage(
  page: { href: string; title: string },
  storage: Pick<Storage, "getItem" | "setItem"> | null | undefined = globalThis.localStorage,
): void {
  rememberVisit(page.href, page.title, storage);
}
