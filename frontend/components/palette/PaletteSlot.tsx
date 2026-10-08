import { headers } from "next/headers";
import { getTranslations } from "next-intl/server";

import { adminSections, type StaffRole } from "../AdminNav";
import { DEV_SECTIONS } from "../DevNav";
import { ORG_SECTIONS } from "../OrgNav";

import { PaletteTrigger } from "./PaletteTrigger";
import { SEARCH_KINDS, type PaletteData, type PaletteLink, type PalettePortal, type PaletteStrings } from "./types";

/** The portal a signed-in screen belongs to, from where its wordmark leads ("/dev", "/org?org=…", "/admin"). */
export function portalOf(homeHref: string): { portal: PalettePortal; query: string } {
  const at = homeHref.indexOf("?");
  const path = at < 0 ? homeHref : homeHref.slice(0, at);
  const query = at < 0 ? "" : homeHref.slice(at);
  if (path.startsWith("/admin")) return { portal: "staff", query: "" };
  if (path.startsWith("/org")) return { portal: "org", query };
  return { portal: "developer", query: "" };
}

/**
 * The top bar's Search (D-67, P25): the button, with what the command palette needs, formatted here on the server so
 * the browser gets plain strings and no message runtime. The palette itself loads on first use (PaletteTrigger).
 */
export async function PaletteSlot({ homeHref, staffRole }: { homeHref: string; staffRole?: StaffRole }) {
  const { portal, query } = portalOf(homeHref);
  const [t, nav, admin, shell] = await Promise.all([
    getTranslations("palette"),
    getTranslations("nav"),
    getTranslations("admin"),
    getTranslations("shell"),
  ]);

  const sections: PaletteLink[] =
    portal === "developer"
      ? DEV_SECTIONS.map(({ key, href }) => ({ id: `go-${key}`, title: nav(key), href }))
      : portal === "org"
        ? ORG_SECTIONS.map(({ key, href }) => ({ id: `go-${key}`, title: nav(key), href: `${href}${query}` }))
        : adminSections(staffRole ?? "admin").map(({ key, href }) => ({ id: `go-${key}`, title: admin(`nav.${key}`), href }));
  const goTo: PaletteLink[] = [
    ...sections,
    { id: "go-settings", title: t("settings"), href: "/settings/security" },
    { id: "go-notifications", title: t("notifications"), href: "/notifications" },
    { id: "go-help", title: shell("help"), href: "/help" },
  ];
  const create: PaletteLink | null =
    portal === "developer"
      ? { id: "act-create", title: t("newProposal"), href: "/dev/ideas/new" }
      : portal === "org"
        ? { id: "act-create", title: t("postBrief"), href: `/org/problems/new${query}` }
        : null;

  const strings: PaletteStrings = {
    trigger: t("trigger"),
    dialog: t("dialog"),
    input: t("input"),
    close: t("close"),
    empty: t("empty", { q: "{q}" }),
    searching: t("searching"),
    unavailable: t("unavailable"),
    results: t("results", { count: "{count}" }),
    goTo: t("goTo"),
    recent: t("recent"),
    actions: t("actions"),
    kind: Object.fromEntries(SEARCH_KINDS.map((kind) => [kind, t(`kind.${kind}`)])) as PaletteStrings["kind"],
    newProposal: t("newProposal"),
    postBrief: t("postBrief"),
    themeDark: t("themeDark"),
    themeLight: t("themeLight"),
    signOut: shell("signOut"),
    signOutFailed: shell("signOutFailed"),
    keyMove: t("keyMove"),
    keyOpen: t("keyOpen"),
    keyNewTab: t("keyNewTab"),
    keyClose: t("keyClose"),
  };
  const data: PaletteData = { portal, goTo, create, strings, shortcut: shortcutFor(await userAgent()) };
  return <PaletteTrigger data={data} />;
}

/** The request's browser, or "" outside a request (a test). */
async function userAgent(): Promise<string> {
  try {
    return (await headers()).get("user-agent") ?? "";
  } catch {
    return "";
  }
}

/** "⌘ K" where the platform's modifier is Command (macOS, iPadOS, iOS), "Ctrl K" elsewhere. */
export function shortcutFor(agent: string): string {
  return /Macintosh|Mac OS X|iPhone|iPad/.test(agent) ? "⌘ K" : "Ctrl K";
}
