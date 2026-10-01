import { getMessages, getTranslations } from "next-intl/server";

import type { StringTree } from "@/components/ClientStrings";
import type en from "@/locales/en.json";

type Messages = typeof en;

// Messages for client components on the signed-in pages, formatted on the server (REQ-UX-05, docs/spec/07 item 5).
// next-intl's client runtime is about 7 KB of gzipped JS on every route that uses it; these pages take plain strings
// instead. Arguments stay as "{name}" placeholders that the client fills in (components/ClientStrings.tsx), so the
// namespaces sent this way use plain arguments only: no plural or select (locales/locales.test.ts checks).

/** Every argument name used by the namespaces formatted here (the locale test keeps this list complete). */
export const PLACEHOLDER_NAMES = [
  "count",
  "current",
  "date",
  "id",
  "limit",
  "max",
  "name",
  "number",
  "org",
  "plan",
  "price",
  "product",
  "step",
  "title",
  "total",
  "value",
  "version",
] as const;

/** Namespaces whose client components read server-formatted strings. */
export const CLIENT_STRING_NAMESPACES = [
  "shell",
  "errorPage",
  "checkout",
  "notificationSettings",
  "ideaEditor",
  "ideaFields",
  "ideaAssistant",
  "ideaDelete",
  "pitch",
  "adminModeration",
  "tagWithdraw",
  "orgProposal",
  "trackerActions",
  "scoutForm",
  "expressInterest",
  "tier2Share",
  "adminResearch",
  "likedNiches",
  "security",
  "password",
  "fields",
  "validation",
  "errors",
  "tour",
] as const;
export type ClientNamespace = (typeof CLIENT_STRING_NAMESPACES)[number];

const PLACEHOLDERS = Object.fromEntries(PLACEHOLDER_NAMES.map((name) => [name, `{${name}}`]));

type Translate = (key: string, values?: Record<string, string>) => string;

/** A message tree formatted in the request's language, placeholders left in. */
function formatTree(t: Translate, node: unknown, prefix: string): StringTree {
  const tree: StringTree = {};
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    // Leaves are messages (precompiled by next-intl's plugin); objects are nested namespaces.
    const nested = value !== null && typeof value === "object" && !Array.isArray(value);
    tree[key] = nested ? formatTree(t, value, path) : t(path, PLACEHOLDERS);
  }
  return tree;
}

/** The namespaces as trees of strings in the request's language, placeholders left in. */
export async function clientStrings(namespaces: readonly ClientNamespace[]): Promise<Record<string, StringTree>> {
  const messages = (await getMessages()) as Record<string, unknown>;
  const out: Record<string, StringTree> = {};
  for (const namespace of namespaces) {
    const t = (await getTranslations(namespace)) as unknown as Translate;
    out[namespace] = formatTree(t, messages[namespace], "");
  }
  return out;
}

/**
 * Chosen messages, or groups of them, of a namespace that is not sent whole: its other messages carry rich-text tags
 * formatted only where they are shown (`pickedStrings("signup", ["passwordHint"])`, the security page's password
 * form), or the client needs only a few of them (`pickedStrings("ideaFields", ["maturityValue"])`, the scout form's
 * maturity labels; docs/spec/07 item 5, the page's weight). Plain messages without arguments only.
 */
export async function pickedStrings<N extends keyof Messages & string>(
  namespace: N,
  keys: readonly (keyof Messages[N] & string)[],
): Promise<Record<N, StringTree>> {
  const messages = (await getMessages()) as Record<string, Record<string, unknown>>;
  const t = (await getTranslations(namespace as never)) as unknown as Translate;
  const chosen = Object.fromEntries(keys.map((key) => [key, messages[namespace][key]]));
  return { [namespace]: formatTree(t, chosen, "") } as Record<N, StringTree>;
}
