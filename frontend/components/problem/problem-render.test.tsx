import { cleanup, render, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SavedExcerpts } from "@/app/(admin)/admin/research/Sections";
import en from "@/locales/en.json";

import { Citations } from "./Citations";
import type { ProblemDetail } from "./problem";
import { ProblemCard } from "./ProblemCard";

// The server components render with the English messages, as next-intl's server functions would give them.
vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

/** Resolves the async server components inside a tree (the client renderer cannot), leaving plain elements. */
async function resolve(node: ReactNode): Promise<ReactNode> {
  if (Array.isArray(node)) return Promise.all(node.map(resolve));
  if (!isValidElement(node)) return node;
  const { type, props } = node as ReactElement<{ children?: ReactNode }>;
  if (typeof type === "function" && type.constructor.name === "AsyncFunction") {
    return resolve(await (type as (p: unknown) => Promise<ReactNode>)(props));
  }
  if (props.children === undefined) return node;
  return cloneElement(node as ReactElement<{ children?: ReactNode }>, {}, await resolve(props.children));
}

const SAFE = "https://www.sasra.go.ke/2026/07/16/strengthening-cyber-resilience-in-the-sacco-industry/";
const UNSAFE = ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "http://www.sasra.go.ke/x"];

const citation = (url: string) => ({
  url,
  publisher: "SACCO Societies Regulatory Authority (SASRA)",
  source_type: "official",
  published_date: "2026-07-16",
  quote: "The Authority remains committed to supporting secure digital transformation.",
});

describe("Citations (REQ-RES-02)", () => {
  it("links a source only when its address is plain https", async () => {
    render(await Citations({ sources: [citation(SAFE), ...UNSAFE.map(citation)], labelledBy: "x" }));
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe(SAFE);
    expect(document.querySelectorAll("[data-citation]")).toHaveLength(4);
    expect(document.querySelectorAll("blockquote[cite]")).toHaveLength(1);
    for (const url of UNSAFE) expect(document.body.innerHTML).not.toContain(url.slice(0, 11));
  });
});

describe("SavedExcerpts (REQ-RES-01)", () => {
  it("links an excerpt's topic only when its address is plain https, and marks freshness with a word and an icon", async () => {
    const excerpt = (id: string, url: string, freshness: "fresh" | "stale" | "archived") => ({
      id,
      niche: "health",
      country: "KE",
      url,
      publisher: "The Star",
      source_type: "news",
      official: false,
      published_date: "2026-01-01",
      retrieved_at: "2026-09-29",
      quote: "A quote.",
      topic: `Topic ${id}`,
      freshness,
    });
    render(
      await SavedExcerpts({
        groups: [
          {
            slug: "health",
            label: "Health",
            excerpts: [
              excerpt("a", SAFE, "fresh"),
              excerpt("b", UNSAFE[0], "stale"),
              excerpt("c", UNSAFE[1], "archived"),
            ],
          },
        ],
        asOf: "2026-09-30",
        total: 3,
      }),
    );
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Topic a"]);
    expect(screen.getByText("Topic b").closest("a")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Saved excerpts (3)" }).closest("summary")).not.toBeNull();
    for (const [key, word] of [
      ["fresh", "Current"],
      ["stale", "Older than 12 months"],
      ["archived", "Archived, not used"],
    ]) {
      const mark = document.querySelector(`[data-freshness="${key}"]`)!;
      expect(mark.textContent).toBe(word);
      expect(mark.querySelector("svg")).not.toBeNull();
    }
  });
});

describe("ProblemCard (REQ-RES-02, docs/spec/06 6.5)", () => {
  const problem: ProblemDetail = {
    id: "01a0f015-0feb-76bd-8eec-21b72f9f10e8",
    title: "Drought losses squeeze grain farmers",
    source: "research_agent",
    label: "Seeded example for the demo (not a live AI result), human-reviewed on 30 Sep 2026",
    niche: { id: "n", slug: "agriculture", label: "Agriculture" },
    statement: "Farmers need better ways to plan planting after dry spells.",
    published_at: "2026-09-30T02:11:47Z",
    affected_group: "Grain farmers",
    country: "KE",
    county_code: null,
    ai_generated: false,
    seeded_example: true,
    confidence: "0.810",
    named_orgs: [],
    citations: [{ ...citation(SAFE), retrieved_at: "2026-09-29T00:00:00Z" }],
  };

  it("says a seeded card is a seeded example, never AI-drafted", async () => {
    render(await resolve(await ProblemCard({ problem })));
    expect(document.querySelector("[data-label]")?.textContent).toBe(
      "Seeded example for the demo (not a live AI result), human-reviewed on 30 Sep 2026",
    );
    expect(screen.queryByText(/AI-drafted/)).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(problem.title);
    expect(screen.getByText("0.81 out of 1")).toBeTruthy();
    expect(screen.getByText("Kenya")).toBeTruthy();
  });

  it("labels a live research card AI-drafted with its review day", async () => {
    render(await resolve(await ProblemCard({ problem: { ...problem, seeded_example: false, ai_generated: true } })));
    expect(document.querySelector("[data-label]")?.textContent).toBe("AI-drafted, human-reviewed on 30 Sep 2026");
  });
});
