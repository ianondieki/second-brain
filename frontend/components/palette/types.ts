// The command palette's data (D-67, P25): what the server gives the top bar's Search button, and what the lazily loaded
// palette shows. Plain, serialisable values: the button carries them in the page's payload, not in its script.

/** Which portal the screen belongs to: it picks the sections, the side's action and the search groups. */
export type PalettePortal = "developer" | "org" | "staff";

/** A place to jump to: a section, a settings page, a recent detail page or a search result. */
export interface PaletteLink {
  id: string;
  title: string;
  subtitle?: string | null;
  href: string;
}

/** The palette's own strings, formatted on the server in the request's language ("{q}" and "{count}" left in). */
export interface PaletteStrings {
  trigger: string;
  dialog: string;
  input: string;
  close: string;
  empty: string;
  searching: string;
  unavailable: string;
  results: string;
  goTo: string;
  recent: string;
  actions: string;
  kind: Record<SearchKind, string>;
  newProposal: string;
  postBrief: string;
  themeDark: string;
  themeLight: string;
  signOut: string;
  signOutFailed: string;
  keyMove: string;
  keyOpen: string;
  keyNewTab: string;
  keyClose: string;
}

/** The groups the API's search answers with (GET /api/me/search). */
export const SEARCH_KINDS = ["ideas", "engagements", "inbox", "problems", "briefs", "companies"] as const;
export type SearchKind = (typeof SEARCH_KINDS)[number];

export interface PaletteData {
  portal: PalettePortal;
  /** The portal's sections, then Settings, Notifications and Help. */
  goTo: PaletteLink[];
  /** New proposal (developer) or Post a Brief (organisation), with its address; none for the staff console. */
  create: PaletteLink | null;
  strings: PaletteStrings;
}
