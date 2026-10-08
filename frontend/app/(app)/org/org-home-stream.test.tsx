import { createTranslator } from "next-intl";
import { isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { ORG_ID, ORG_NAME } from "@/test/briefs";

import OrganisationHome from "./page";

// P25 (REQ-UX-05, acceptance 2): the organisation Home's server render waits only for the session and the membership
// (the greeting, its LCP photograph and the one primary action). The tiles and the lists, which share their reads,
// stream in through one Suspense boundary that nothing follows, so the greeting flushes first and nothing moves.

const { reads, pending } = vi.hoisted(() => {
  const reads = { started: [] as string[] };
  const pending = (name: string) => () => {
    reads.started.push(name);
    return new Promise(() => undefined);
  };
  return { reads, pending };
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
  getInbox: pending("inbox"),
}));
vi.mock("./scout-data", () => ({ getMatches: pending("matches") }));
vi.mock("@/components/tracker/data", () => ({ orgEngagements: pending("engagements") }));
vi.mock("./brief-data", () => ({ getBriefs: pending("briefs") }));
vi.mock("@/components/activity/fetch", () => ({ getActivity: pending("activity") }));

/** The elements of a tree, server components unresolved (what the shell renders), depth first. */
function elements(node: ReactNode, found: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) node.forEach((child) => elements(child, found));
  else if (isValidElement(node)) {
    found.push(node);
    elements((node.props as { children?: ReactNode }).children, found);
  }
  return found;
}

describe("the organisation Home's first flush", () => {
  it("sends the greeting without waiting for the tiles' and the lists' reads", async () => {
    const page = (await OrganisationHome({ searchParams: Promise.resolve({}) } as never)) as ReactElement<{ children: ReactNode }>;
    const shell = elements(page.props.children);
    const boundaries = shell.filter((element) => element.type === Suspense) as ReactElement<{ fallback: ReactNode; children: ReactNode }>[];
    expect(boundaries).toHaveLength(1);
    expect(boundaries[0].props.fallback).toBeNull();
    expect(reads.started).toEqual([]);
    // The boundary is the last thing in its column, and the column the last thing on the page.
    const column = shell.find((element) => (element.props as { children?: ReactNode[] }).children instanceof Array && (element.props as { className?: string }).className?.includes("flex-col"))!;
    const kids = ((column.props as { children: ReactNode[] }).children).flat().filter(isValidElement);
    expect(kids[kids.length - 1]).toBe(boundaries[0]);
    const top = (page.props.children as ReactNode[]).flat().filter(isValidElement);
    expect(top[top.length - 1]).toBe(column);
    // Its content reads the tiles' four lists and the calendar together.
    const body = boundaries[0].props.children as ReactElement;
    void (body.type as (props: unknown) => Promise<ReactNode>)(body.props);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(reads.started.sort()).toEqual(["activity", "briefs", "engagements", "inbox", "matches"]);
  });
});
