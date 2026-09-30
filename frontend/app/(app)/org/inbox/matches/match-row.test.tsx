import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { Match } from "../../scout";
import { MatchRow } from "./MatchRow";

// REQ-SCOUT-02 (docs/spec/06 6.1, 6.8; docs/spec/07 item 2): a match shows the developer's pseudonymous handle only,
// at most two chips, why it matches with who wrote it; an unavailable match shows no teaser and no why.

afterEach(cleanup);

const MATCH: Match = {
  id: "0192a7c4-0000-7000-8000-0000000000m1",
  scout_id: "s1",
  proposal_id: "p1",
  available: true,
  owner_handle: "jacaranda-otter-17",
  teaser: {
    title: "Maziwa baridi",
    niche: { id: "n1", slug: "microfinance-saccos", label: "Financial services › Microfinance & SACCOs" },
    country: "KE",
    county_code: "KE-47",
    maturity: "mvp",
    ask: "pilot",
    problem_statement: "Milk spoils overnight.",
    impact_claims: null,
    summary: "Shared solar chillers.",
  },
  niche: { id: "n1", slug: "microfinance-saccos", label: "Financial services › Microfinance & SACCOs" },
  score: 82,
  why: "Mentions sacco and fits the niche.",
  why_source: "model",
  demo_fallback: false,
  injection_suspected: false,
  created_at: "2026-09-30T05:00:00Z",
  digest_sent_at: null,
  feedback: null,
  feedback_reason: null,
};

describe("a scout match in the Inbox", () => {
  it("shows the handle, niche, fit and why, with at most two chips", () => {
    renderWithIntl(<MatchRow match={MATCH} href="/org/inbox/matches/m1" />);
    const row = document.querySelector("[data-match]")!;
    expect(screen.getByRole("link", { name: "Maziwa baridi" }).getAttribute("href")).toBe("/org/inbox/matches/m1");
    expect(row.textContent).toContain("By jacaranda-otter-17");
    expect(row.textContent).toContain("Financial services › Microfinance & SACCOs");
    expect(row.textContent).toContain("Fit 82 out of 100");
    expect(row.textContent).toContain("Mentions sacco and fits the niche.");
    expect(row.querySelector("[data-why-source]")!.textContent).toContain(en.scoutMatches.whySource.model);
    expect(row.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
  });

  it("labels a demo fallback's why as the rules'", () => {
    renderWithIntl(<MatchRow match={{ ...MATCH, why_source: "code", demo_fallback: true }} href="/x" />);
    expect(document.querySelector("[data-why-source]")!.textContent).toContain(en.scoutMatches.whySource.demoFallback);
  });

  it("shows an unavailable match as unavailable: no teaser, no why, no handle", () => {
    renderWithIntl(
      <MatchRow
        match={{ ...MATCH, available: false, teaser: null, why: null, owner_handle: null, why_source: "code" }}
        href="/x"
      />,
    );
    const row = document.querySelector("[data-match]")!;
    expect(row.getAttribute("data-available")).toBe("false");
    expect(row.textContent).toContain(en.scoutMatches.unavailable);
    expect(row.textContent).toContain(en.scoutMatches.unavailableTitle);
    expect(row.textContent).not.toContain("Maziwa baridi");
    expect(row.textContent).not.toContain("Mentions sacco");
    expect(row.textContent).not.toContain("jacaranda-otter-17");
    expect(row.querySelector("[data-why-source]")).toBeNull();
  });
});
