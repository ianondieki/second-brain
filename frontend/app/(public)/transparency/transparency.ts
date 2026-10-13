import { serverApi } from "@/lib/api/server";
import type { components } from "@/lib/api/schema";

// The public transparency reads (REQ-AUD-01; P28 track D): GET /api/transparency (the signed daily roots over the
// audit chain heads, newest first) and GET /.well-known/provenance-keys.json (the Ed25519 keys that sign them; retired
// keys stay listed). Both are public and per address unlimited, so no session cookie and no forwarded address is sent.
// Bounded, so a slow API ends in "try again" for that part rather than a page that never renders. A failed read is
// null; an empty list is a real answer (no root has been published yet).

export type TransparencyRoot = components["schemas"]["TransparencyRoot"];
export type ProvenanceKey = components["schemas"]["ProvenanceKey"];

/** At most this many roots are shown: a month of days, newest first. */
export const ROOTS_SHOWN = 30;

/** The text each root's signature covers (bridge/provenance/signing.root_message), with its two parts named. */
export const ROOT_MESSAGE = "bridge-transparency-root-v1:<day>:<root>";

/** The same roots as the API serves them, for anyone checking with their own tools (proxied like every /api path). */
export const ROOTS_HREF = `/api/transparency?limit=${ROOTS_SHOWN}`;

export interface TransparencyRead {
  roots: TransparencyRoot[] | null;
  keys: ProvenanceKey[] | null;
}

/** Bounded and never cached: a new day's root shows on the next visit. */
const bounded = () => ({ signal: AbortSignal.timeout(4000), cache: "no-store" as const });

export async function readRoots(): Promise<TransparencyRoot[] | null> {
  try {
    const { data } = await serverApi().GET("/api/transparency", {
      params: { query: { limit: ROOTS_SHOWN } },
      ...bounded(),
    });
    if (!data || !Array.isArray(data.roots)) return null;
    // Newest first, whatever order arrives; never more than a month.
    return [...data.roots].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0)).slice(0, ROOTS_SHOWN);
  } catch {
    return null;
  }
}

export async function readKeys(): Promise<ProvenanceKey[] | null> {
  try {
    const { data } = await serverApi().GET("/.well-known/provenance-keys.json", bounded());
    if (!data || !Array.isArray(data.keys)) return null;
    // Keys in use first, then retired ones, newest first within each.
    return [...data.keys].sort(
      (a, b) => Number(a.retired_at !== null) - Number(b.retired_at !== null) || b.created_at.localeCompare(a.created_at),
    );
  } catch {
    return null;
  }
}

/** Both reads at once: a page that waits for the slower of the two, never for one after the other. */
export async function readTransparency(): Promise<TransparencyRead> {
  const [roots, keys] = await Promise.all([readRoots(), readKeys()]);
  return { roots, keys };
}

/** A key's anchor on the page ("ed25519:e60c…" becomes "key-ed25519-e60c…"), so a root's key id links to its key. */
export function keyAnchor(kid: string): string {
  return `key-${kid.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}
