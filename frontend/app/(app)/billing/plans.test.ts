import { describe, expect, it } from "vitest";

import { billingSubject, formatKes, planLines, priceKind, rowAction, sameLinesAs, type Plan } from "./plans";

const ORG_A = "0192a7c4-5b1e-7c3d-8e9f-00000000000a";
const ORG_B = "0192a7c4-5b1e-7c3d-8e9f-00000000000b";

function plan(over: Partial<Plan> & Pick<Plan, "code">): Plan {
  return {
    side: "developer",
    name: over.code,
    price_kes_minor: 0,
    interval: "none",
    limits: {},
    is_default: false,
    purchasable: false,
    upgrade_to: null,
    ...over,
  };
}

// The developer ladder of backend/config/plans.yaml, trimmed to what the screen reads.
const DEV: Plan[] = [
  plan({
    code: "dev_free",
    is_default: true,
    upgrade_to: "dev_pro_monthly",
    limits: {
      active_proposals: 3,
      tags_per_proposal: 5,
      followed_niches: 1,
      recommendations_with_explanations: false,
      viewer_analytics: false,
    },
  }),
  plan({
    code: "dev_pro_monthly",
    price_kes_minor: 49900,
    interval: "month",
    purchasable: true,
    limits: {
      active_proposals: null,
      tags_per_proposal: 20,
      followed_niches: 5,
      recommendations_with_explanations: true,
      viewer_analytics: true,
      whatsapp_reminders: "release-2",
    },
  }),
  plan({ code: "dev_pro_yearly", price_kes_minor: 499000, interval: "year", purchasable: true }),
  plan({ code: "dev_student" }),
];

describe("billingSubject", () => {
  const member = (org_id: string, roles: string[], org_name = "Maji Co") => ({ org_id, org_name, roles }) as never;

  it("is the developer's own plan without ?org=", () => {
    expect(billingSubject({ side: "developer", memberships: [] }, undefined)).toEqual({ kind: "developer" });
  });

  it("is an organisation the person pays for when ?org= names it", () => {
    const me = { side: "org" as const, memberships: [member(ORG_A, ["reviewer"]), member(ORG_B, ["finance"])] };
    expect(billingSubject(me, ORG_B.toUpperCase())).toMatchObject({ kind: "org", membership: { org_id: ORG_B } });
    expect(billingSubject(me, ORG_A)).toMatchObject({ kind: "notPayer", membership: { org_id: ORG_A } });
  });

  it("never switches to another organisation when ?org= is not one of the person's", () => {
    const me = { side: "org" as const, memberships: [member(ORG_A, ["owner"])] };
    expect(billingSubject(me, ORG_B)).toEqual({ kind: "notMember" });
    expect(billingSubject(me, "not-a-uuid")).toEqual({ kind: "notMember" });
    expect(billingSubject(me, [ORG_B, ORG_A])).toEqual({ kind: "notMember" });
  });

  it("picks the first organisation an organisation member pays for", () => {
    const me = { side: "org" as const, memberships: [member(ORG_A, ["reviewer"]), member(ORG_B, ["admin"])] };
    expect(billingSubject(me, undefined)).toMatchObject({ kind: "org", membership: { org_id: ORG_B } });
    expect(billingSubject({ side: "org", memberships: [member(ORG_A, ["signatory"])] }, "")).toMatchObject({
      kind: "notPayer",
    });
    expect(billingSubject({ side: "org", memberships: [] }, undefined)).toEqual({ kind: "noOrg" });
  });
});

describe("prices", () => {
  it("formats KES minor units with grouping and cents only when there are any", () => {
    expect(formatKes(49900, "en")).toBe("499");
    expect(formatKes(125000000, "en")).toBe("1,250,000");
    expect(formatKes(125050, "en")).toBe("1,250.50");
  });

  it("words free, monthly, yearly and plans not sold here", () => {
    expect(DEV.map(priceKind)).toEqual(["free", "perMonth", "perYear", "notSold"]);
    expect(priceKind(plan({ code: "x", purchasable: true, price_kes_minor: 100 }))).toBe("once");
  });
});

describe("planLines", () => {
  it("says what the Free plan allows", () => {
    expect(planLines(DEV[0])).toEqual([
      { key: "activeProposals", count: 3 },
      { key: "tagsPerProposal", count: 5 },
      { key: "followedNiches", count: 1 },
    ]);
  });

  it("words unlimited caps and lists only features the plan really has", () => {
    expect(planLines(DEV[1])).toEqual([
      { key: "activeProposalsUnlimited" },
      { key: "tagsPerProposal", count: 20 },
      { key: "followedNiches", count: 5 },
      { key: "recommendations" },
      { key: "viewerAnalytics" },
    ]);
  });

  it("reads the organisation limits", () => {
    const growth = plan({
      code: "org_growth",
      side: "org",
      limits: {
        seats: 20,
        scout_agents: 5,
        full_unlocks_per_month: null,
        problem_briefs: null,
        csv_export: true,
        pipeline_analytics: "coming-soon",
      },
    });
    expect(planLines(growth)).toEqual([
      { key: "seats", count: 20 },
      { key: "scoutAgents", count: 5 },
      { key: "unlocksUnlimited" },
      { key: "briefsUnlimited" },
      { key: "csvExport" },
    ]);
  });

  it("skips values it cannot read", () => {
    expect(planLines(plan({ code: "x", limits: { active_proposals: "many", tags_per_proposal: -1 } }))).toEqual([]);
  });
});

describe("sameLinesAs", () => {
  it("points a plan that allows the same as an earlier one to the first of them", () => {
    const pro = DEV[1].limits;
    const ladder = [DEV[0], DEV[1], { ...DEV[2], limits: pro }, { ...DEV[3], limits: pro }];
    expect(sameLinesAs(ladder)).toEqual([null, null, "dev_pro_monthly", "dev_pro_monthly"]);
  });

  it("never points plans without lines at each other", () => {
    expect(sameLinesAs([plan({ code: "a" }), plan({ code: "b" })])).toEqual([null, null]);
  });
});

describe("rowAction", () => {
  it("offers the next plan up as the upgrade and later plans as choices, never a downgrade", () => {
    expect(DEV.map((p) => rowAction(DEV, "dev_free", p))).toEqual(["current", "upgrade", "choose", null]);
    expect(DEV.map((p) => rowAction(DEV, "dev_pro_monthly", p))).toEqual([null, "current", "choose", null]);
    expect(DEV.map((p) => rowAction(DEV, "dev_pro_yearly", p))).toEqual([null, null, "current", null]);
  });
});
