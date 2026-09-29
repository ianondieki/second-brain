"use client";

import { createContext, useCallback, useContext, type ReactNode } from "react";

import type en from "@/locales/en.json";

// Server-formatted strings for client components (lib/i18n/client-strings.ts), instead of next-intl's client
// runtime: a context, a lookup and a placeholder fill. No string is concatenated: a message's "{name}" slots are
// filled from values, as next-intl would.

export type StringTree = { [key: string]: string | StringTree };
type Messages = typeof en;

/** "a.b.c" paths of a message tree's leaves. */
type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

const Strings = createContext<Record<string, StringTree>>({});

/** Provides namespaces of strings to the client components below; nested providers add to their parent's. */
export function ClientStrings({ strings, children }: { strings: Record<string, StringTree>; children: ReactNode }) {
  const parent = useContext(Strings);
  return <Strings value={{ ...parent, ...strings }}>{children}</Strings>;
}

/** Fills "{name}" slots from values; a slot without a value stays as it is. */
export function fill(template: string, values?: Record<string, string | number>): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (slot, name: string) => (name in values ? String(values[name]) : slot));
}

/** Like next-intl's useTranslations: `t("key.path", { name })`. A missing message shows its key. */
export function useStrings<N extends keyof Messages>(namespace: N) {
  const tree = useContext(Strings)[namespace];
  return useCallback(
    (key: Leaves<Messages[N]>, values?: Record<string, string | number>): string => {
      let node: string | StringTree | undefined = tree;
      for (const part of (key as string).split(".")) node = typeof node === "object" ? node[part] : undefined;
      return typeof node === "string" ? fill(node, values) : `${String(namespace)}.${key as string}`;
    },
    [tree, namespace],
  );
}
