import { describe, expect, it } from "vitest";

import { brief } from "@/test/briefs";

import {
  bodyOf,
  briefHref,
  briefRefusalOf,
  briefStats,
  briefUpgrade,
  checkBrief,
  closable,
  EMPTY_DRAFT,
  newBriefHref,
  planFull,
  postsBriefs,
  problemsHref,
  todayInNairobi,
  wordCount,
  type BriefDraft,
} from "./briefs";
import type { Membership } from "./membership";

// REQ-DIR-05 (docs/spec/06 6.2 last bullet, 6.5; plan limits docs/spec/05): the Problems section's plain logic. The
// API decides every rule again; these decide what the screens offer and how a refusal is worded.

const ORG = "01a0ee62-0000-7000-8000-00000000000a";
const OTHER = "01a0ee62-0000-7000-8000-00000000000b";
const NICHE = "01a0f067-99ac-71a6-8c49-822887f625e2";
const BRIEF = "01a0f070-0000-7000-8000-000000000001";
const one: Membership[] = [{ org_id: ORG, org_name: "Telco A (fixture)", roles: ["reviewer"] }];
const two: Membership[] = [...one, { org_id: OTHER, org_name: "SACCO B (fixture)", roles: ["owner", "admin"] }];

const draft = (extra: Partial<BriefDraft> = {}): BriefDraft => ({
  ...EMPTY_DRAFT,
  title: "Tower sites go dark when fuel runs out",
  statement: "Field teams learn about empty generator tanks only after the site stops working.",
  niche: NICHE,
  ...extra,
});

describe("the Problems section's links", () => {
  it("keeps the chosen organisation only for members of several", () => {
    expect(problemsHref(one, ORG)).toBe("/org/problems");
    expect(problemsHref(two, OTHER)).toBe(`/org/problems?org=${OTHER}`);
    expect(problemsHref(one, ORG, { posted: true })).toBe("/org/problems?posted=1");
    expect(problemsHref(one, ORG, { cursor: "abc" })).toBe("/org/problems?cursor=abc");
    expect(briefHref(two, OTHER, BRIEF)).toBe(`/org/problems/${BRIEF}?org=${OTHER}`);
    expect(newBriefHref(one, ORG)).toBe("/org/problems/new");
  });

  it("offers posting to owners, admins, signatories and reviewers only", () => {
    for (const role of ["owner", "admin", "signatory", "reviewer"] as const) {
      expect(postsBriefs({ org_id: ORG, org_name: "A", roles: [role] }), role).toBe(true);
    }
    expect(postsBriefs({ org_id: ORG, org_name: "A", roles: ["finance"] })).toBe(false);
    expect(postsBriefs({ org_id: ORG, org_name: "A", roles: [] })).toBe(false);
  });

  it("closes only a published Brief (one in review is 409 brief_not_published)", () => {
    expect(closable(brief({ state: "in_review" }))).toBe(false);
    expect(closable(brief({ state: "published" }))).toBe(true);
    expect(closable(brief({ state: "closed" }))).toBe(false);
    expect(closable(brief({ state: "rejected" }))).toBe(false);
  });
});

describe("the brief form's checks", () => {
  const today = "2026-10-02";

  it("passes a complete draft", () => {
    expect(checkBrief(draft(), today)).toEqual({});
    expect(checkBrief(draft({ deadline: today }), today)).toEqual({}); // today is allowed
  });

  it("asks for the title, the statement and the niche", () => {
    expect(checkBrief({ ...EMPTY_DRAFT, title: "   " }, today)).toEqual({
      title: "titleRequired",
      statement: "statementRequired",
      niche: "nicheRequired",
    });
  });

  it("keeps the ProblemCard's lengths, counting characters as the API does", () => {
    expect(checkBrief(draft({ title: "a".repeat(91) }), today).title).toBe("tooLong");
    expect(checkBrief(draft({ title: `  ${"a".repeat(90)}  ` }), today).title).toBeUndefined();
    expect(checkBrief(draft({ statement: "b".repeat(1201) }), today).statement).toBe("tooLong");
    expect(checkBrief(draft({ affected: "c".repeat(201) }), today).affected).toBe("tooLong");
    // At most 120 words, within the 1,200 characters.
    expect(checkBrief(draft({ statement: Array(120).fill("dry").join(" ") }), today).statement).toBeUndefined();
    expect(checkBrief(draft({ statement: Array(121).fill("dry").join(" ") }), today).statement).toBe("tooManyWords");
    expect(checkBrief(draft({ title: "🐄".repeat(90) }), today).title).toBeUndefined(); // code points, not UTF-16
  });

  it("refuses a past deadline and anything that is not a date", () => {
    expect(checkBrief(draft({ deadline: "2026-10-01" }), today).deadline).toBe("deadlinePast");
    expect(checkBrief(draft({ deadline: "01/11/2026" }), today).deadline).toBe("deadlineInvalid");
  });

  it("counts words for the statement's meter", () => {
    expect(wordCount("")).toBe(0);
    expect(wordCount("  generators   run\ndry ")).toBe(3);
  });

  it("knows today in Nairobi, not in UTC", () => {
    expect(todayInNairobi(new Date("2026-10-01T21:30:00Z"))).toBe("2026-10-02"); // 00:30 in Nairobi
    expect(todayInNairobi(new Date("2026-10-01T20:59:00Z"))).toBe("2026-10-01");
  });

  it("sends a public Brief with blank optional fields as null", () => {
    expect(bodyOf(draft({ title: "  Tower sites  ", affected: "  " }))).toEqual({
      title: "Tower sites",
      statement: "Field teams learn about empty generator tanks only after the site stops working.",
      affected_group: null,
      niche_id: NICHE,
      county_code: null,
      budget_band: null,
      deadline: null,
      visibility: "public",
    });
    expect(bodyOf(draft({ county: "KE-30", band: "kes_100k_1m", deadline: "2026-11-30" }))).toMatchObject({
      county_code: "KE-30",
      budget_band: "kes_100k_1m",
      deadline: "2026-11-30",
    });
  });
});

describe("a Briefs refusal", () => {
  const body = (code: string, extra: Record<string, unknown> = {}) => ({ detail: { code, message: "never shown", ...extra } });

  it("names the next plan up and the limit for a 402, never a URL from the body", () => {
    const refused = briefRefusalOf(
      402,
      body("plan_limit", { limit: 1, used: 1, upgrade: { plan: "org_starter", url: "https://evil.example/pay" } }),
    );
    expect(refused).toMatchObject({ refusal: "planLimit", upgradePlan: "org_starter", limit: 1, fields: [] });
    expect(briefRefusalOf(402, body("plan_limit", { upgrade: null }))).toMatchObject({ upgradePlan: null, limit: null });
  });

  it.each([
    [403, "verification_required", "verification"],
    [403, "role_required", "forbidden"],
    [422, "visibility_not_available", "visibility"],
    [409, "brief_closed", "closed"],
    [409, "brief_not_published", "notPublished"],
    [409, "brief_frozen", "frozen"],
    [429, "briefs_daily_limit", "dailyLimit"],
    [403, "org_unavailable", "orgUnavailable"],
    [404, "not_found", "notFound"],
    [403, "mfa_enrolment_required", "mfaSetup"],
    [401, "mfa_required", "mfaCode"],
    [500, undefined, "generic"],
  ])("words a %i %s as %s", (status, code, refusal) => {
    expect(briefRefusalOf(status, code ? body(code) : undefined).refusal).toBe(refusal);
  });

  it("maps a 422 invalid_brief's fields to the form's, each once, unknown codes as other", () => {
    const refused = briefRefusalOf(
      422,
      body("invalid_brief", {
        errors: [
          { field: "statement", code: "contains_phone", message: "x" },
          { field: "statement", code: "too_long", message: "x" },
          { field: "affected_group", code: "something_new", message: "x" },
          { field: "deadline", code: "deadline_past", message: "x" },
          { field: "secret", code: "blank", message: "x" },
          "not an item",
        ],
      }),
    );
    expect(refused.refusal).toBe("invalid");
    expect(refused.fields).toEqual([
      { field: "statement", code: "contains_phone" },
      { field: "affected", code: "other" },
      { field: "deadline", code: "deadline_past" },
    ]);
  });
});

describe("the plan and Home's figures", () => {
  it("says when the plan is full", () => {
    expect(planFull({ problem_briefs: 1, used: 1 })).toBe(true);
    expect(planFull({ problem_briefs: 5, used: 1 })).toBe(false);
    expect(planFull({ problem_briefs: null, used: 40 })).toBe(false);
  });

  it("counts open Briefs as the plan does, and those in review and their proposals from the page", () => {
    const stats = briefStats({
      plan: { plan: "org_starter", problem_briefs: 5, used: 2 },
      items: [
        brief({ state: "in_review" }),
        brief({ state: "published", proposal_count: 3 }),
        brief({ state: "closed", proposal_count: 4 }),
        brief({ state: "rejected" }),
      ],
    });
    expect(stats).toEqual({ open: 2, inReview: 1, proposals: 3 });
  });

  const plans = [
    { code: "org_claimed", name: "Claimed (Free)", purchasable: false, upgrade_to: "org_starter", limits: { problem_briefs: 1 } },
    { code: "org_starter", name: "Starter", purchasable: true, upgrade_to: "org_growth", limits: { problem_briefs: 5 } },
    { code: "org_growth", name: "Growth", purchasable: true, upgrade_to: null, limits: { problem_briefs: null } },
  ];

  it("finds the next plan up with more open Briefs, and none at the top", () => {
    expect(briefUpgrade(plans, "org_claimed")?.code).toBe("org_starter");
    expect(briefUpgrade(plans, "org_starter")?.code).toBe("org_growth");
    expect(briefUpgrade(plans, "org_growth")).toBeNull();
    expect(briefUpgrade(plans, "unknown")).toBeNull();
  });
});
