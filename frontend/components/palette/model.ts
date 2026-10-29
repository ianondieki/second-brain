import type { SearchGroup } from "./search";
import type { PaletteData, PaletteLink } from "./types";

// What the palette lists for a query (pure, so it is tested without a browser): Go to and Actions filtered here, Recent
// filtered here, the search groups as the API answered (already matched there). Empty groups are left out.

export type PaletteAction = "theme" | "signout";

export interface PaletteOption extends PaletteLink {
  /** An action runs instead of opening an address. */
  action?: PaletteAction;
}

export interface PaletteGroup {
  id: string;
  label: string;
  options: PaletteOption[];
}

/** Lower case without accents, so "Kenyan" finds "kenyan" and "Wanjiru" finds "Wanjirũ". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Where the query appears in a title: [before, match, after], or null (no query, or not in the title). */
export function matchParts(title: string, query: string): [string, string, string] | null {
  const q = fold(query.trim());
  if (!q) return null;
  // Folding can change lengths ("ũ" is one character either way once composed), so the index is searched on the
  // folded title of the same length; titles whose folding changes their length fall back to no highlight.
  const folded = fold(title);
  if (folded.length !== title.length) return null;
  const at = folded.indexOf(q);
  if (at < 0) return null;
  return [title.slice(0, at), title.slice(at, at + q.length), title.slice(at + q.length)];
}

const matches = (option: PaletteLink, query: string) => !query.trim() || fold(option.title).includes(fold(query.trim()));

export function paletteGroups({
  data,
  query,
  recent,
  results,
  dark,
}: {
  data: PaletteData;
  query: string;
  recent: PaletteLink[];
  results: SearchGroup[];
  /** The page is dark now: the theme action offers light. */
  dark: boolean;
}): PaletteGroup[] {
  const s = data.strings;
  const actions: PaletteOption[] = [
    ...(data.create ? [data.create] : []),
    { id: "act-theme", title: dark ? s.themeLight : s.themeDark, href: "", action: "theme" },
    { id: "act-signout", title: s.signOut, href: "", action: "signout" },
  ];
  const groups: PaletteGroup[] = [
    { id: "go", label: s.goTo, options: data.goTo.filter((o) => matches(o, query)) },
    { id: "recent", label: s.recent, options: recent.filter((o) => matches(o, query)) },
    ...results.map((group) => ({ id: group.kind, label: s.kind[group.kind], options: group.items })),
    { id: "actions", label: s.actions, options: actions.filter((o) => matches(o, query)) },
  ];
  return groups.filter((group) => group.options.length > 0);
}
