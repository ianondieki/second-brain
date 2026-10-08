import { SEARCH_KINDS, type PaletteLink, type SearchKind } from "./types";

// The palette's search (GET /api/me/search?q=; D-67, P25). The route was built beside this palette (P25-B), after
// backend/openapi.json was frozen for this worktree, so its answer is read as unknown and checked here, field by
// field, instead of trusting a hand-written type: anything that does not have the documented shape
// `{q, groups: [{kind, items: [{id, title, subtitle, href}]}]}` is dropped, and a failed call shows no search groups.
// Once the regenerated schema is merged (P25 part 2), this reads the route through the typed client instead.

export const SEARCH_MIN = 2;
export const SEARCH_MAX = 80;
export const SEARCH_DEBOUNCE_MS = 180;
const PER_GROUP = 5;

export interface SearchGroup {
  kind: SearchKind;
  items: PaletteLink[];
}

const isKind = (value: unknown): value is SearchKind => typeof value === "string" && (SEARCH_KINDS as readonly string[]).includes(value);

/** Only this site's own paths: a result never sends anyone to another origin. */
const isLocalPath = (value: unknown): value is string => typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\");

/** The groups of a search answer that have the documented shape; nothing else. */
export function parseSearch(body: unknown): SearchGroup[] {
  if (!body || typeof body !== "object") return [];
  const groups = (body as { groups?: unknown }).groups;
  if (!Array.isArray(groups)) return [];
  const out: SearchGroup[] = [];
  for (const group of groups) {
    if (!group || typeof group !== "object") continue;
    const { kind, items } = group as { kind?: unknown; items?: unknown };
    if (!isKind(kind) || !Array.isArray(items) || out.some((g) => g.kind === kind)) continue;
    const links: PaletteLink[] = [];
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      const { id, title, subtitle, href } = item as Record<string, unknown>;
      if (typeof id !== "string" || typeof title !== "string" || !title || !isLocalPath(href)) continue;
      links.push({ id: `${kind}-${id}`, title, subtitle: typeof subtitle === "string" && subtitle ? subtitle : null, href });
      if (links.length === PER_GROUP) break;
    }
    if (links.length > 0) out.push({ kind, items: links });
  }
  return out;
}

/** The query as the API takes it (trimmed, at most 80 characters), or null when it is too short to send. */
export function searchQuery(text: string): string | null {
  const q = text.trim().slice(0, SEARCH_MAX);
  return q.length >= SEARCH_MIN ? q : null;
}

/** One search: the groups, or none when the call fails, answers anything but 200, or is aborted. */
export async function search(q: string, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<SearchGroup[]> {
  try {
    const response = await fetcher(`/api/me/search?q=${encodeURIComponent(q)}`, {
      credentials: "same-origin",
      headers: { accept: "application/json" },
      signal,
    });
    if (!response.ok) return [];
    return parseSearch(await response.json());
  } catch {
    return [];
  }
}
