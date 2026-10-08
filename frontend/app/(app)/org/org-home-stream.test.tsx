import { createTranslator } from "next-intl";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { briefList, ORG_ID, ORG_NAME } from "@/test/briefs";

import { GreetingBand } from "../dev/GreetingBand";

import OrganisationHome from "./page";

// P25 (REQ-UX-05, acceptance 2): the organisation Home's first flush is the greeting (its LCP photograph, the one
// primary action) and the four stat tiles. The calendar's read starts with the tiles' four; the calendar and the two
// lists under it stream in through one Suspense boundary, the last thing on the page, so nothing painted moves.

const { reads, pending, answered } = vi.hoisted(() => {
  const reads = { started: [] as string[] };
  const pending = (name: string) => () => {
    reads.started.push(name);
    return new Promise(() => undefined);
  };
  const answered = (name: string, value: unknown) => async () => {
    reads.started.push(name);
    return value;
  };
  return { reads, pending, answered };
});

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }), headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn(), unstable_rethrow: () => undefined }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("@/lib/api/server", () => ({ appNow: () => "2026-10-08T06:30:00Z" }));
vi.mock("./data", () => ({
  orgContext: async () => ({
    me: { user: { display_name: "Rita Njeri" }, mfa: { enrolled: true, required: true, verified: true } },
    memberships: [{ org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] }],
    org: { org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] },
    missing: null,
    query: "",
  }),
  getInbox: answered("inbox", { kind: "page", page: { items: [], next_cursor: null, held_count: 0, verification: "e2" } }),
}));
vi.mock("./scout-data", () => ({ getMatches: answered("matches", { kind: "ok", value: [] }) }));
vi.mock("@/components/tracker/data", () => ({ orgEngagements: answered("engagements", { ok: true, value: [] }) }));
vi.mock("./brief-data", () => ({
  getBriefs: async () => {
    reads.started.push("briefs");
    return { kind: "ok", value: briefList() };
  },
}));
vi.mock("@/components/activity/fetch", () => ({ getActivity: pending("activity") }));

/** The elements of a tree outside any Suspense boundary (server components unresolved: what the shell renders). */
function shell(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) node.forEach((child) => shell(child, found));
  else if (isValidElement(node)) {
    found.push(node);
    if (node.type !== Suspense) shell((node.props as { children?: ReactNode }).children, found);
  }
  return found;
}

describe("the organisation Home's first flush", () => {
  it("sends the greeting and the tiles, and streams the calendar and the lists last", async () => {
    const page = (await OrganisationHome({ searchParams: Promise.resolve({}) } as never)) as ReactElement<{ children: ReactNode }>;
    const top = shell(page.props.children);
    expect(top.some((element) => element.type === GreetingBand)).toBe(true);
    expect(top.filter((element) => element.type === Suspense)).toHaveLength(0);
    const bodyElement = top.find((element) => "org" in (element.props as object) && "memberships" in (element.props as object))!;
    // The body resolves although the calendar's read never answers: only the tiles' four are waited for.
    const body = (await (bodyElement.type as (props: unknown) => Promise<ReactNode>)(bodyElement.props)) as ReactElement<{ children: ReactNode }>;
    expect([...reads.started].sort()).toEqual(["activity", "briefs", "engagements", "inbox", "matches"]);
    expect(reads.started[0]).toBe("activity"); // started first, before the tiles' reads are awaited
    const outside = shell(body);
    expect(outside.some((element) => (element.props as Record<string, unknown>)["data-home"] === "stats")).toBe(true);
    const boundaries = outside.filter((element) => element.type === Suspense) as ReactElement<{ fallback: ReactNode }>[];
    expect(boundaries).toHaveLength(1);
    expect(boundaries[0].props.fallback).toBeNull();
    const kids = [body.props.children].flat(3).filter(isValidElement);
    expect(kids[kids.length - 1]).toBe(boundaries[0]);
    // The body is the last thing in its column, and the column the last thing on the page.
    const column = top.find((element) => [(element.props as { children?: ReactNode }).children].flat(3).includes(bodyElement))!;
    const columnKids = [(column.props as { children: ReactNode }).children].flat(3).filter(isValidElement);
    expect(columnKids[columnKids.length - 1]).toBe(bodyElement);
    const pageKids = [page.props.children].flat(3).filter(isValidElement);
    expect(pageKids[pageKids.length - 1]).toBe(column);
  });
});
