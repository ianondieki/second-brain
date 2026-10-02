import { createTranslator } from "next-intl";
import { isValidElement, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { PortalNavFor } from "@/components/PortalNavFor";
import { ProblemCard } from "@/components/problem/ProblemCard";
import { SignedInShell } from "@/components/SignedInShell";
import en from "@/locales/en.json";

import ProblemPage from "./page";

// The problem card page keeps the portal's navigation and the full content width (ux review round 2, item 16).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
const mocks = vi.hoisted(() => ({ me: vi.fn(), problem: vi.fn(), counties: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ requireMe: mocks.me }));
vi.mock("@/components/problem/data", () => ({ getProblem: mocks.problem, getCountyNames: mocks.counties }));

type ShellProps = { homeHref: string; nav?: ReactElement; wide?: boolean };

async function page(side: "developer" | "org") {
  mocks.me.mockResolvedValue({ side, mfa: { enrolled: true, verified: true, required: false }, user: {} });
  mocks.problem.mockResolvedValue(null);
  mocks.counties.mockResolvedValue(new Map());
  const element = await ProblemPage({ params: Promise.resolve({ id: "p-1" }), searchParams: Promise.resolve({}) } as never);
  expect(isValidElement(element) && element.type).toBe(SignedInShell);
  return (element as ReactElement<ShellProps>).props;
}

describe("the problem card page", () => {
  it.each(["developer", "org"] as const)("renders in the %s portal's shell with its navigation and the full width", async (side) => {
    const props = await page(side);
    expect(props.homeHref).toBe(side === "org" ? "/org" : "/dev");
    expect(props.wide).toBe(true);
    expect(isValidElement(props.nav) && props.nav.type).toBe(PortalNavFor);
  });
});

describe("the problem card's region", () => {
  it("passes the county's name for the problem's county code to the card", async () => {
    mocks.me.mockResolvedValue({ side: "developer", mfa: { enrolled: true, verified: true, required: false }, user: {} });
    mocks.problem.mockResolvedValue({ id: "p-1", title: "A Brief", county_code: "KE-30", country: "KE", citations: [] });
    mocks.counties.mockResolvedValue(new Map([["KE-30", "Nairobi City"]]));
    const element = await ProblemPage({ params: Promise.resolve({ id: "p-1" }), searchParams: Promise.resolve({}) } as never);
    const found: Array<{ countyName?: string | null }> = [];
    const walk = (node: unknown) => {
      if (Array.isArray(node)) node.forEach(walk);
      else if (isValidElement(node)) {
        const props = node.props as { countyName?: string | null; children?: unknown };
        if (node.type === ProblemCard) found.push(props);
        walk(props.children);
      }
    };
    walk((element as ReactElement<{ children?: unknown }>).props.children);
    expect(found.map((props) => props.countyName)).toEqual(["Nairobi City"]);
  });
});
