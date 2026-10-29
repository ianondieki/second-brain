import { RECENT_MAX } from "./remember";
import type { PaletteLink } from "./types";

// The command palette's "Recent" group (D-67, P25): the account's last five detail pages in this browser, by their
// address and the title already on their screen (remember.ts writes them under the account's key). Nothing else about
// the page; storage that is full, blocked or holding something unreadable is ignored.

function valid(entry: unknown): entry is PaletteLink {
  if (!entry || typeof entry !== "object") return false;
  const { href, title } = entry as Record<string, unknown>;
  return typeof href === "string" && href.startsWith("/") && !href.startsWith("//") && typeof title === "string" && title.length > 0;
}

/** The account's remembered pages, newest first; none without a key (the account could not be read). */
export function readRecent(key: string | null, storage: Pick<Storage, "getItem"> | null | undefined = globalThis.localStorage): PaletteLink[] {
  if (!key) return [];
  try {
    const parsed: unknown = JSON.parse(storage?.getItem(key) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(valid)
      .slice(0, RECENT_MAX)
      .map(({ href, title }) => ({ id: `recent-${href}`, title, href }));
  } catch {
    return [];
  }
}
