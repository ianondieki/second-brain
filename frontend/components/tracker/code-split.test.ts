import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// docs/spec/07 item 5 (150 KB of JS per route; REQ-ENG-11): the tracker's page and the Messages route each carry only
// their own client code. Walks every module each screen reaches through static imports (relative and "@/" paths;
// `import type` is erased and dynamic `import()` is a separate chunk, so neither counts), and checks that the
// tracker's page never reaches the thread (components/tracker/messages/*) and the Messages route never reaches the
// turn card's buttons (Actions.tsx).

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const STATIC_IMPORT = /^\s*(?:import|export)(?!\s+type\b)(?:[^;"']*?\sfrom\s+)?["']([^"']+)["']/gm;

function resolveImport(from: string, specifier: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = join(FRONTEND, specifier.slice(2));
  else if (specifier.startsWith(".")) base = resolve(dirname(from), specifier);
  else return null; // a package
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")]) {
    if (existsSync(candidate) && /\.(ts|tsx)$/.test(candidate)) return candidate;
  }
  return null; // JSON and other assets
}

/** Every module reached from `entry`, as paths relative to frontend/. */
export function reachable(entry: string): Set<string> {
  const seen = new Set<string>();
  const queue = [join(FRONTEND, entry)];
  while (queue.length > 0) {
    const file = queue.pop()!;
    const name = relative(FRONTEND, file);
    if (seen.has(name)) continue;
    seen.add(name);
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(STATIC_IMPORT)) {
      const target = resolveImport(file, match[1]);
      if (target) queue.push(target);
    }
  }
  return seen;
}

describe("the tracker's routes", () => {
  it("never reach the thread from the tracker's page", () => {
    const tracker = reachable("components/tracker/EngagementScreen.tsx");
    expect(tracker.has("components/tracker/Actions.tsx")).toBe(true); // the walk follows the page's own imports
    expect([...tracker].filter((name) => name.startsWith("components/tracker/messages/"))).toEqual([]);
    expect(tracker.has("components/tracker/MessagesTab.tsx")).toBe(false);
  });

  it("never reach the turn card's buttons from the Messages route", () => {
    for (const entry of [
      "components/tracker/MessagesScreen.tsx",
      "app/(app)/dev/engagements/[id]/messages/page.tsx",
      "app/(app)/org/engagements/[id]/messages/page.tsx",
    ]) {
      const messages = reachable(entry);
      expect(messages.has("components/tracker/messages/Thread.tsx"), entry).toBe(true);
      expect(messages.has("components/tracker/Actions.tsx"), entry).toBe(false);
      expect(messages.has("components/tracker/EngagementScreen.tsx"), entry).toBe(false);
    }
  });
});
