import en from "@/locales/en.json";

import type { PaletteData } from "./types";

// A developer's palette as PaletteSlot builds it, with the English strings (for tests).
const p = en.palette;
export const DEV_PALETTE: PaletteData = {
  portal: "developer",
  goTo: [
    { id: "go-home", title: "Home", href: "/dev" },
    { id: "go-discover", title: "Discover", href: "/dev/discover" },
    { id: "go-ideas", title: "My ideas", href: "/dev/ideas" },
    { id: "go-engagements", title: "Engagements", href: "/dev/engagements" },
    { id: "go-companies", title: "Companies", href: "/dev/companies" },
    { id: "go-settings", title: p.settings, href: "/settings/security" },
    { id: "go-notifications", title: p.notifications, href: "/notifications" },
    { id: "go-help", title: en.shell.help, href: "/help" },
  ],
  create: { id: "act-create", title: p.newProposal, href: "/dev/ideas/new" },
  shortcut: "Ctrl K",
  recentKey: "wazo-recent:v2:account-a",
  strings: {
    trigger: p.trigger,
    dialog: p.dialog,
    input: p.input,
    close: p.close,
    empty: p.empty,
    searching: p.searching,
    unavailable: p.unavailable,
    results: p.results,
    goTo: p.goTo,
    recent: p.recent,
    actions: p.actions,
    kind: p.kind,
    newProposal: p.newProposal,
    postBrief: p.postBrief,
    themeDark: p.themeDark,
    themeLight: p.themeLight,
    signOut: en.shell.signOut,
    signOutFailed: en.shell.signOutFailed,
    keyMove: p.keyMove,
    keyOpen: p.keyOpen,
    keyNewTab: p.keyNewTab,
    keyClose: p.keyClose,
  },
};

/** GET /api/me/search?q=sacco as the API answers it for the demo developer (the shape P25-B builds). */
export const SEARCH_SACCO = {
  q: "sacco",
  groups: [
    {
      kind: "ideas",
      items: [{ id: "i1", title: "Repayment nudges for SACCO members", subtitle: "Published", href: "/dev/ideas/i1" }],
    },
    {
      kind: "problems",
      items: [{ id: "p1", title: "SACCO members miss loan repayments", subtitle: "Financial services", href: "/problems/p1" }],
    },
  ],
};
