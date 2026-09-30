import { getMessages, getTranslations } from "next-intl/server";

import type { StringTree } from "@/components/ClientStrings";

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
  "ideaEditor",
  "ideaFields",
  "ideaAssistant",
  "ideaDelete",
  "pitch",
  "tagWithdraw",
  "orgProposal",
  "trackerActions",
] as const;
export type ClientNamespace = (typeof CLIENT_STRING_NAMESPACES)[number];

const PLACEHOLDERS = Object.fromEntries(PLACEHOLDER_NAMES.map((name) => [name, `{${name}}`]));

type Translate = (key: string, values?: Record<string, string>) => string;

/** The namespaces as trees of strings in the request's language, placeholders left in. */
export async function clientStrings(namespaces: readonly ClientNamespace[]): Promise<Record<string, StringTree>> {
  const messages = (await getMessages()) as Record<string, unknown>;
  const out: Record<string, StringTree> = {};
  for (const namespace of namespaces) {
    const t = (await getTranslations(namespace)) as unknown as Translate;
    const walk = (node: unknown, prefix: string): StringTree => {
      const tree: StringTree = {};
      for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
        const path = prefix ? `${prefix}.${key}` : key;
        // Leaves are messages (precompiled by next-intl's plugin); objects are nested namespaces.
        const nested = value !== null && typeof value === "object" && !Array.isArray(value);
        tree[key] = nested ? walk(value, path) : t(path, PLACEHOLDERS);
      }
      return tree;
    };
    out[namespace] = walk(messages[namespace], "");
  }
  return out;
}
