import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { Membership } from "../../membership";
import type { CompareItem } from "../../shortlist";
import { CompareView } from "./compare/CompareView";
import { CompareBar } from "./CompareBar";

// REQ-REPO-02 (P21 B4): choosing 2 to 4 shortlisted proposals and comparing them on their Tier-1 facts only.

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }) }));

beforeEach(() => push.mockReset());
afterEach(cleanup);

const labels = {
  compare: "Compare",
  chosen: "{count} of 4 chosen",
  hint: "Choose 2 to 4 proposals to compare.",
  tooFew: "Choose at least 2 proposals to compare.",
  tooMany: "Choose at most 4 proposals to compare.",
};

function renderBar(ids: string[], action = "/org/inbox/shortlist/compare") {
  renderWithIntl(
    <form>
      {ids.map((id) => (
        <input key={id} type="checkbox" name="ids" value={id} aria-label={`Compare ${id}`} />
      ))}
      <CompareBar action={action} labels={labels} />
    </form>,
  );
}

describe("the shortlist's Compare", () => {
  it("is the one primary action and counts what is chosen", () => {
    renderBar(["a", "b", "c"]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe(labels.hint);
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare a" }));
    expect(screen.getByRole("status").textContent).toBe("1 of 4 chosen");
  });

  it("keeps the press until 2 are chosen, then opens the page at its short address", () => {
    renderBar(["a", "b", "c"], "/org/inbox/shortlist/compare?org=o2");
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare a" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(labels.tooFew);
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare c" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(push).toHaveBeenCalledWith("/org/inbox/shortlist/compare?org=o2&ids=a,c");
  });

  it("says when more than 4 are chosen", () => {
    renderBar(["a", "b", "c", "d", "e"]);
    for (const id of ["a", "b", "c", "d", "e"]) fireEvent.click(screen.getByRole("checkbox", { name: `Compare ${id}` }));
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(labels.tooMany);
  });
});

const org: Membership = { org_id: "o1", org_name: "Telco A", roles: ["viewer"] };
const ITEMS: CompareItem[] = [
  {
    proposal_id: "p1",
    title: "Maziwa baridi",
    niche: { id: "n1", slug: "agriculture", label: "Agriculture" },
    country: "KE",
    county_code: "KE-32",
    maturity: "mvp",
    ask: "pilot",
    cert_id: "CERT1",
    registered_at: "2026-10-01T08:00:00Z",
    engagement: { id: "e1", state: "UNDER_REVIEW" },
    fit_score: 82,
  },
  {
    proposal_id: "p2",
    title: null,
    niche: null,
    country: "KE",
    county_code: null,
    maturity: null,
    ask: null,
    cert_id: null,
    registered_at: null,
    engagement: null,
    fit_score: null,
  },
];

describe("the compare view", () => {
  it("lays the facts out as a table (1024 px and up) and as one card per proposal", () => {
    renderWithIntl(
      <CompareView items={ITEMS} memberships={[org]} org={org} counties={[{ code: "KE-32", name: "Nakuru" }]} />,
    );
    const table = document.querySelector("[data-compare=table] table")!;
    const headers = within(table as HTMLElement).getAllByRole("columnheader");
    expect(headers.map((th) => th.textContent)).toEqual(["Maziwa baridi", en.inbox.untitled]);
    const rows = within(table as HTMLElement).getAllByRole("rowheader").map((th) => th.textContent);
    expect(rows).toEqual(Object.values(en.shortlist.fact));
    const first = document.querySelectorAll("[data-compare=cards] > li")[0] as HTMLElement;
    expect(within(first).getByRole("link", { name: "Maziwa baridi" }).getAttribute("href")).toBe("/org/inbox/p1");
    expect(first.querySelector("[data-fact=place] dd")?.textContent).toBe("Nakuru");
    expect(first.querySelector("[data-fact=fit] dd")?.textContent).toContain("Fit 82 out of 100");
    expect(first.querySelector("[data-fact=engagement] a")?.getAttribute("href")).toBe("/org/engagements/e1");
    const second = document.querySelectorAll("[data-compare=cards] > li")[1] as HTMLElement;
    // The County row of a proposal without a county says so, never its country (P21 ux review).
    expect(second.querySelector("[data-fact=place] dd")?.textContent).toBe(en.inbox.notStated);
    expect(second.querySelector("[data-fact=engagement] dd")?.textContent).toBe(en.shortlist.noEngagement);
    expect(second.querySelector("[data-fact=fit] dd")?.textContent).toBe(en.shortlist.notMatched);
  });
});
