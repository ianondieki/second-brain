import { describe, expect, it, vi } from "vitest";

import { DEV_PALETTE, SEARCH_SACCO } from "./fixtures";
import { fold, matchParts, paletteGroups } from "./model";
import { isDetailPath, readRecent, RECENT_KEY, RECENT_MAX, rememberPage } from "./recent";
import { parseSearch, search, searchQuery } from "./search";

// D-67 (P25): what the command palette lists, from the API's answer, this browser's recent pages and the query.

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), data };
}

describe("parseSearch", () => {
  it("keeps the documented shape, at most five per group, prefixed ids", () => {
    const groups = parseSearch(SEARCH_SACCO);
    expect(groups.map((g) => g.kind)).toEqual(["ideas", "problems"]);
    expect(groups[0].items[0]).toEqual({
      id: "ideas-i1",
      title: "Repayment nudges for SACCO members",
      subtitle: "Published",
      href: "/dev/ideas/i1",
    });
    const many = { groups: [{ kind: "companies", items: Array.from({ length: 9 }, (_, i) => ({ id: `c${i}`, title: `Co ${i}`, subtitle: null, href: `/dev/companies/c${i}` })) }] };
    expect(parseSearch(many)[0].items).toHaveLength(5);
  });

  it("drops unknown kinds, malformed items and any address off this site", () => {
    const groups = parseSearch({
      groups: [
        { kind: "secrets", items: [{ id: "x", title: "x", href: "/x" }] },
        {
          kind: "problems",
          items: [
            { id: "a", title: "Elsewhere", href: "https://evil.example/" },
            { id: "b", title: "Protocol-relative", href: "//evil.example/" },
            { id: "c", title: "Script", href: "javascript:alert(1)" },
            { id: "d", title: "", href: "/problems/d" },
            { id: 5, title: "No id", href: "/problems/e" },
            { id: "f", title: "Kept", href: "/problems/f" },
          ],
        },
        "nonsense",
      ],
    });
    expect(groups).toEqual([{ kind: "problems", items: [{ id: "problems-f", title: "Kept", subtitle: null, href: "/problems/f" }] }]);
    expect(parseSearch(null)).toEqual([]);
    expect(parseSearch({ groups: "no" })).toEqual([]);
  });

  it("sends trimmed queries of two to eighty characters only", () => {
    expect(searchQuery(" a ")).toBeNull();
    expect(searchQuery(" sa ")).toBe("sa");
    expect(searchQuery("x".repeat(100))).toHaveLength(80);
  });

  it("answers null (unavailable) when the call fails or is refused, and no groups for an empty answer", async () => {
    const signal = new AbortController().signal;
    expect(await search("sacco", signal, vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline")))).toBeNull();
    expect(await search("sacco", signal, vi.fn<typeof fetch>().mockResolvedValue(new Response("", { status: 429 })))).toBeNull();
    expect(await search("sacco", signal, vi.fn<typeof fetch>().mockResolvedValue(new Response("", { status: 503 })))).toBeNull();
    expect(await search("sacco", signal, vi.fn<typeof fetch>().mockResolvedValue(new Response("not json")))).toBeNull();
    expect(await search("sacco", signal, vi.fn<typeof fetch>().mockResolvedValue(new Response('{"q":"sacco","groups":[]}')))).toEqual([]);
  });
});

describe("recent pages", () => {
  it("knows a detail page from a list, an editor or a form", () => {
    expect(isDetailPath("/dev/ideas/3f1c")).toBe(true);
    expect(isDetailPath("/org/engagements/e-1")).toBe(true);
    expect(isDetailPath("/problems/p1")).toBe(true);
    expect(isDetailPath("/dev/ideas")).toBe(false);
    expect(isDetailPath("/dev/ideas/new")).toBe(false);
    expect(isDetailPath("/org/inbox/shortlist")).toBe(false);
    expect(isDetailPath("/settings/security")).toBe(false);
  });

  it("keeps five, newest first, one entry per address", () => {
    const storage = memoryStorage();
    for (let i = 1; i <= 7; i += 1) rememberPage({ href: `/dev/ideas/${i}`, title: `Idea ${i}` }, storage);
    rememberPage({ href: "/dev/ideas/5", title: "Idea 5 renamed" }, storage);
    const recent = readRecent(storage);
    expect(recent).toHaveLength(RECENT_MAX);
    expect(recent.map((r) => r.title)).toEqual(["Idea 5 renamed", "Idea 7", "Idea 6", "Idea 4", "Idea 3"]);
  });

  it("ignores unreadable or foreign entries and storage that fails", () => {
    expect(readRecent(memoryStorage({ [RECENT_KEY]: "{oops" }))).toEqual([]);
    expect(readRecent(memoryStorage({ [RECENT_KEY]: JSON.stringify([{ href: "https://x.example", title: "x" }, { href: "/dev", title: "Home" }]) }))).toEqual([
      { id: "recent-/dev", title: "Home", href: "/dev" },
    ]);
    const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(readRecent(throwing)).toEqual([]);
    expect(() => rememberPage({ href: "/dev/ideas/1", title: "x" }, throwing)).not.toThrow();
  });
});

describe("paletteGroups", () => {
  it("lists Go to and Actions with no query, Recent when there is one, and the API's groups for the query", () => {
    const base = { data: DEV_PALETTE, recent: [], results: [], dark: false };
    expect(paletteGroups({ ...base, query: "" }).map((g) => g.id)).toEqual(["go", "actions"]);
    const recent = [{ id: "recent-/dev/ideas/1", title: "SACCO nudges", href: "/dev/ideas/1" }];
    const results = parseSearch(SEARCH_SACCO);
    const groups = paletteGroups({ ...base, query: "sacco", recent, results });
    expect(groups.map((g) => g.label)).toEqual(["Recent", "Your ideas", "Problems"]);
  });

  it("offers the other appearance, and Post a Brief to an organisation", () => {
    const actions = (dark: boolean, data = DEV_PALETTE) =>
      paletteGroups({ data, query: "", recent: [], results: [], dark }).find((g) => g.id === "actions")!.options.map((o) => o.title);
    expect(actions(false)).toContain("Switch to dark appearance");
    expect(actions(true)).toContain("Switch to light appearance");
    const org = { ...DEV_PALETTE, portal: "org" as const, create: { id: "act-create", title: "Post a Brief", href: "/org/problems/new" } };
    expect(actions(false, org)[0]).toBe("Post a Brief");
  });

  it("matches without case or accents and marks where", () => {
    expect(fold("Wanjirũ")).toBe("wanjiru");
    expect(matchParts("Engagements", "GAGE")).toEqual(["En", "gage", "ments"]);
    expect(matchParts("Wanjirũ Kamau", "wanjiru")).toEqual(["", "Wanjirũ", " Kamau"]);
    expect(matchParts("Home", "")).toBeNull();
    expect(matchParts("Home", "xyz")).toBeNull();
  });
});
