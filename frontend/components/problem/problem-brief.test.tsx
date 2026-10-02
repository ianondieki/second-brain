import { cleanup, render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { BAND, BRIEF_ID, NICHE, ORG_ID, ORG_NAME } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";

import { listedProblemLabel, problemLabel, type ProblemDetail } from "./problem";
import { ProblemCard } from "./ProblemCard";
import { ProblemLabelText } from "./ProblemLabelText";
import { ProblemStart } from "./ProblemStart";

// REQ-DIR-05 (docs/spec/06 6.5 ProblemCard labels): an organisation's Problem Brief reads "Posted by <organisation>"
// on every screen, and its card carries the budget band and the deadline the organisation gave.

vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

const ORG = { id: ORG_ID, slug: "telco-a-fixture", name: ORG_NAME };

function detail(extra: Partial<ProblemDetail> = {}): ProblemDetail {
  return {
    id: BRIEF_ID,
    title: "Tower sites go dark when fuel runs out",
    statement: "Field teams learn about empty generator tanks only after the site stops working.",
    affected_group: "Rural subscribers",
    ai_generated: false,
    citations: [],
    confidence: null,
    country: "KE",
    county_code: "KE-30",
    label: `Posted by ${ORG_NAME}`,
    named_orgs: [],
    niche: NICHE,
    published_at: "2026-10-01T09:00:00+03:00",
    seeded_example: false,
    source: "org_brief",
    org: ORG,
    brief: { org: ORG, budget_band: BAND, deadline: "2026-11-30", open: true },
    ...extra,
  };
}

describe("a Brief's label", () => {
  it("names the organisation that posted it, and nothing when the organisation is not in the directory", () => {
    expect(problemLabel(detail(), "en")).toEqual({ key: "org_brief", org: ORG_NAME });
    expect(problemLabel(detail({ org: null }), "en")).toBeNull();
    expect(listedProblemLabel({ source: "org_brief", label: `Posted by ${ORG_NAME}`, org: ORG }, "en")).toEqual({
      key: "org_brief",
      org: ORG_NAME,
    });
    // Without the organisation the API's own words are shown as they are.
    expect(listedProblemLabel({ source: "org_brief", label: `Posted by ${ORG_NAME}` }, "en")).toEqual({
      key: "api",
      text: `Posted by ${ORG_NAME}`,
    });
  });

  it("reads Posted by <organisation> in a row's meta line", () => {
    renderWithIntl(<ProblemLabelText problem={{ source: "org_brief", label: "ignored", org: ORG }} />);
    expect(document.querySelector("[data-label='org_brief']")?.textContent).toBe(`Posted by ${ORG_NAME}`);
  });
});

describe("starting a proposal from a problem page", () => {
  it("offers the Brief's own action while the organisation is still asking for proposals", async () => {
    render(await ProblemStart({ problem: detail() }));
    const start = screen.getByRole("link", { name: "Start a proposal from this Brief" });
    expect(start.getAttribute("href")).toBe(`/dev/ideas/new?problem=${BRIEF_ID}`);
    expect(start.hasAttribute("data-primary")).toBe(true);
    expect(document.querySelector("[data-brief-ended]")).toBeNull();
  });

  // The API decides why on the platform clock (brief.ended): the page never compares dates itself.
  it.each([
    ["past_deadline", "2026-10-01", "This Brief’s deadline passed on 1 Oct 2026, so the organisation is no longer asking for proposals. You can still start one from the problem.", "past_deadline"],
    ["closed (it wins over a passed deadline)", "2020-01-31", en.problem.briefEnded.closed, "closed"],
    ["closed before its deadline", "2999-12-31", en.problem.briefEnded.closed, "closed"],
    ["absent (an older API): no guess, even with a passed deadline", "2020-01-31", en.problem.briefEnded.notOpen, "absent"],
    ["null while not published", null, en.problem.briefEnded.notOpen, null],
  ] as const)("offers the plain action when ended is %s, and says why quietly", async (_, deadline, sentence, ended) => {
    const brief = { org: ORG, budget_band: BAND, deadline, open: false, ...(ended === "absent" ? {} : { ended }) };
    render(await ProblemStart({ problem: detail({ brief }) }));
    expect(screen.getByRole("link", { name: "Start a proposal from this problem" }).getAttribute("href")).toBe(
      `/dev/ideas/new?problem=${BRIEF_ID}`,
    );
    expect(screen.queryByRole("link", { name: "Start a proposal from this Brief" })).toBeNull();
    expect(document.querySelector("[data-brief-ended]")?.textContent).toBe(sentence);
  });

  it("says nothing while the Brief is open (ended null), deadline today included", async () => {
    render(await ProblemStart({ problem: detail({ brief: { org: ORG, budget_band: BAND, deadline: "2026-10-02", open: true, ended: null } }) }));
    expect(screen.getByRole("link", { name: "Start a proposal from this Brief" })).toBeTruthy();
    expect(document.querySelector("[data-brief-ended]")).toBeNull();
  });

  it("offers the plain action, with no note, for any other problem", async () => {
    render(await ProblemStart({ problem: detail({ source: "developer", org: null, brief: null }) }));
    expect(screen.getByRole("link", { name: "Start a proposal from this problem" })).toBeTruthy();
    expect(document.querySelector("[data-brief-ended]")).toBeNull();
  });
});

describe("a Brief's problem card", () => {
  it("shows the label, the band and the deadline beside the other facts", async () => {
    render(await ProblemCard({ problem: detail() }));
    expect(document.querySelector("[data-label='org_brief']")?.textContent).toBe(`Posted by ${ORG_NAME}`);
    const facts = document.querySelector("dl")!;
    expect(within(facts).getByText("Budget band").nextElementSibling?.textContent).toBe(BAND.label);
    expect(within(facts).getByText("Proposals wanted by").nextElementSibling?.textContent).toBe("30 Nov 2026");
  });

  it("says when the organisation gave no band or deadline", async () => {
    render(await ProblemCard({ problem: detail({ brief: { org: ORG, budget_band: null, deadline: null, open: true } }) }));
    expect(screen.getByText("Budget band").nextElementSibling?.textContent).toBe(en.problem.budgetOpen);
    expect(screen.getByText("Proposals wanted by").nextElementSibling?.textContent).toBe(en.problem.noDeadline);
  });

  it("shows no Brief facts on another problem", async () => {
    render(await ProblemCard({ problem: detail({ source: "developer", label: "Developer-reported", org: null, brief: null }) }));
    expect(screen.queryByText("Budget band")).toBeNull();
    expect(document.querySelector("[data-label]")?.textContent).toBe("Developer-reported");
  });
});
