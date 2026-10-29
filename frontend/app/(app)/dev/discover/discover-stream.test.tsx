import { createTranslator } from "next-intl";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";

// P25 (REQ-UX-05, acceptance 2: LCP ≤ 2.5 s on /dev/discover): the hero's lead is the LCP element, and it needs no
// data. Discover's own render waits only for the session; the filters and the list wait for their reads inside one
// Suspense boundary, the last thing in the page, so the shell and the hero flush first and nothing painted moves.

const ME = { side: "developer", user: { display_name: "Amina" }, mfa: { enrolled: true, required: false, verified: true } } as unknown as Me;
const reads = vi.hoisted(() => ({ started: [] as string[] }));
const pending = (name: string) => () => {
  reads.started.push(name);
  return new Promise(() => undefined);
};

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ requireMe: async () => ME }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("./data", () => ({ trending: pending("trending"), opportunityGap: pending("gap"), briefs: pending("briefs"), savedSearches: pending("saved") }));
vi.mock("@/app/(app)/dev/companies/directory", () => ({ directoryOptions: pending("directory") }));

describe("Discover's first flush", () => {
  it("sends the hero without waiting for the filters' and the list's reads", async () => {
    const { default: DiscoverPage } = await import("./page");
    // Resolves although no read below the hero ever answers.
    const page = (await DiscoverPage({ searchParams: Promise.resolve({}) } as never)) as ReactElement<{ children: ReactNode }>;
    const main = (page.type as (props: unknown) => ReactElement<{ children: ReactNode[] }>)(page.props);
    const children = (main.props.children as ReactNode[]).flat().filter(isValidElement);
    const last = children[children.length - 1] as ReactElement<{ fallback: ReactNode; children: ReactNode }>;
    expect(last.type).toBe(Suspense);
    expect(last.props.fallback).toBeNull();
    expect(children.filter((child) => child.type === Suspense)).toHaveLength(1);
    expect(reads.started).toEqual([]); // the reads start when the boundary renders, not before the shell
    // The hero is in the shell, with its lead.
    expect(JSON.stringify(children[0])).toContain(en.discover.lead);
    // The boundary's content reads the list, the filters' options and the saved searches together.
    const body = last.props.children as ReactElement;
    void (body.type as (props: unknown) => Promise<ReactNode>)(body.props);
    expect(reads.started.sort()).toEqual(["directory", "saved", "trending"]);
  });
});
