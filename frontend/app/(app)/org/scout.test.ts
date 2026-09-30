import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import type { Membership } from "./membership";
import {
  bodyOf,
  checkDraft,
  draftOf,
  interestReasonOf,
  interestRefusalOf,
  matchesHref,
  matchHref,
  parseDraft,
  parseKeywords,
  planFor,
  pruneDraft,
  scoutHref,
  scoutRefusalOf,
  whySourceOf,
  type Scout,
  type ScoutPlan,
} from "./scout";

const A: Membership = { org_id: "01a0ee62-0000-7000-8000-00000000000a", org_name: "Amani Foods", roles: ["admin"] };
const B: Membership = { org_id: "01a0ee62-0000-7000-8000-00000000000b", org_name: "Baraka Bank", roles: ["reviewer"] };
const MATCH = "01a0ee62-f783-733e-9321-9f34ec389ac2";
const NICHE = "01a0ee62-0000-7000-8000-0000000000a1";
const REVIEWER = "01a0ee62-0000-7000-8000-0000000000c1";

const PLAN: ScoutPlan = { plan: "org_free", scout_agents: 1, frequencies: ["weekly"], digest_size: 3 };

describe("links to the scout screens (the EM3 digest links open these, docs/spec/06 6.8)", () => {
  it("keep the chosen organisation only for members of several", () => {
    expect(matchesHref([A], A.org_id)).toBe("/org/inbox?tab=matches");
    expect(matchesHref([A, B], B.org_id)).toBe(`/org/inbox?org=${B.org_id}&tab=matches`);
    expect(matchHref([A], A.org_id, MATCH)).toBe(`/org/inbox/matches/${MATCH}`);
    expect(matchHref([A, B], A.org_id, MATCH)).toBe(`/org/inbox/matches/${MATCH}?org=${A.org_id}`);
    expect(scoutHref([A], A.org_id)).toBe("/org/inbox/scouts/new");
    expect(scoutHref([A, B], A.org_id, NICHE)).toBe(`/org/inbox/scouts/${NICHE}?org=${A.org_id}`);
    expect(scoutHref([A], A.org_id, undefined, { restore: true })).toBe("/org/inbox/scouts/new?restore=1");
    expect(scoutHref([A, B], A.org_id, NICHE, { restore: true })).toBe(
      `/org/inbox/scouts/${NICHE}?org=${A.org_id}&restore=1`,
    );
  });

  it("encode ids so a path segment can never be escaped", () => {
    expect(matchHref([A], A.org_id, "../x?y")).toBe("/org/inbox/matches/..%2Fx%3Fy");
  });
});

describe("keywords typed as one list", () => {
  it("split on commas and new lines, trim, collapse spaces and drop repeats whatever their case", () => {
    expect(parseKeywords(" M-Pesa,  mobile   money\nSACCO, m-pesa ,,\n")).toEqual(["m-pesa", "mobile money", "sacco"]);
    expect(parseKeywords("   ")).toEqual([]);
  });
});

describe("the scout form", () => {
  it("starts at the plan's weekly scout, min_fit 60, in English, for a new scout", () => {
    expect(draftOf(undefined, PLAN)).toEqual({
      niches: [],
      counties: [],
      include: "",
      exclude: "",
      maturity: [],
      minFit: "60",
      frequency: "weekly",
      language: "en",
      recipients: [],
    });
    expect(draftOf(undefined, { ...PLAN, frequencies: ["on_new"] }).frequency).toBe("on_new");
  });

  it("starts from the saved scout when editing", () => {
    const scout = {
      niches: [{ id: NICHE, slug: "microfinance-saccos", label: "Financial services › Microfinance & SACCOs" }],
      counties: ["KE-47"],
      include_keywords: ["sacco", "loans"],
      exclude_keywords: ["crypto"],
      maturity: ["mvp"],
      min_fit: 70,
      frequency: "daily",
      language: "sw",
      recipients: [REVIEWER],
    } as unknown as Scout;
    expect(draftOf(scout, PLAN)).toEqual({
      niches: [NICHE],
      counties: ["KE-47"],
      include: "sacco, loans",
      exclude: "crypto",
      maturity: ["mvp"],
      minFit: "70",
      frequency: "daily",
      language: "sw",
      recipients: [REVIEWER],
    });
  });

  it("asks for one to five niches, at most 20 keywords of 60 characters and a fit from 0 to 100", () => {
    const ok = { ...draftOf(undefined, PLAN), niches: [NICHE] };
    expect(checkDraft(ok)).toEqual({});
    expect(checkDraft({ ...ok, niches: [] })).toEqual({ niches: "nichesRequired" });
    expect(checkDraft({ ...ok, niches: ["1", "2", "3", "4", "5", "6"] })).toEqual({ niches: "nichesMax" });
    const many = Array.from({ length: 21 }, (_, i) => `k${i}`).join(",");
    expect(checkDraft({ ...ok, include: many })).toEqual({ include: "tooMany" });
    expect(checkDraft({ ...ok, exclude: "x".repeat(61) })).toEqual({ exclude: "tooLong" });
    for (const minFit of ["", "-1", "101", "6.5", "abc"]) expect(checkDraft({ ...ok, minFit }), minFit).toEqual({ minFit: "minFit" });
    expect(checkDraft({ ...ok, minFit: " 0 " })).toEqual({});
  });

  it("sends the form as the API's ScoutForm, the budget band left as it is", () => {
    const draft = {
      ...draftOf(undefined, PLAN),
      niches: [NICHE],
      include: "sacco, Loans",
      exclude: "",
      minFit: "75",
      maturity: ["idea" as const],
      recipients: [REVIEWER],
    };
    const body = bodyOf(draft);
    expect(body).toEqual({
      niches: [NICHE],
      counties: [],
      include_keywords: ["sacco", "loans"],
      exclude_keywords: [],
      maturity: ["idea"],
      min_fit: 75,
      frequency: "weekly",
      language: "en",
      recipients: [REVIEWER],
    });
    expect("budget_band" in body).toBe(false);
  });
});

describe("a scout refused by the API", () => {
  const planLimit = { detail: { code: "plan_limit", message: "", upgrade: { plan: "org_growth_monthly" } } };

  it("names the next plan up on a 402, so the screen links to its checkout", () => {
    expect(scoutRefusalOf(402, planLimit)).toEqual({ refusal: "planLimit", upgradePlan: "org_growth_monthly" });
    expect(scoutRefusalOf(402, { detail: { code: "plan_limit", upgrade: null } })).toEqual({
      refusal: "planLimit",
      upgradePlan: null,
    });
  });

  it("words each form refusal by its code, never the server's text", () => {
    const code = (c: string) => ({ detail: { code: c, message: "server text" } });
    expect(scoutRefusalOf(422, code("unknown_niche")).refusal).toBe("unknownNiche");
    expect(scoutRefusalOf(422, code("unknown_county")).refusal).toBe("unknownCounty");
    expect(scoutRefusalOf(422, code("invalid_recipients")).refusal).toBe("invalidRecipients");
    expect(scoutRefusalOf(422, { detail: [{ loc: ["body", "min_fit"] }] }).refusal).toBe("invalid");
    expect(scoutRefusalOf(403, code("forbidden")).refusal).toBe("forbidden");
    expect(scoutRefusalOf(403, code("mfa_enrolment_required")).refusal).toBe("mfaSetup");
    expect(scoutRefusalOf(401, code("mfa_required")).refusal).toBe("mfaCode");
    expect(scoutRefusalOf(404, code("not_found")).refusal).toBe("notFound");
    expect(scoutRefusalOf(500, undefined).refusal).toBe("generic");
  });
});

describe("a match on the screen", () => {
  it("says who wrote its why: the model, the rules, or the rules because the model was a demo fallback", () => {
    expect(whySourceOf({ why_source: "model", demo_fallback: false })).toBe("model");
    expect(whySourceOf({ why_source: "code", demo_fallback: false })).toBe("code");
    expect(whySourceOf({ why_source: "code", demo_fallback: true })).toBe("demoFallback");
  });

  it("keeps Express interest's refusal reasons to the API's codes", () => {
    expect(interestReasonOf({ allowed: true, reason: null })).toBeNull();
    for (const reason of ["org_not_e2", "org_unavailable", "role_required", "engagement_exists", "proposal_unavailable"]) {
      expect(interestReasonOf({ allowed: false, reason })).toBe(reason);
    }
    expect(interestReasonOf({ allowed: false, reason: "something_new" })).toBe("other");
    expect(interestReasonOf({ allowed: false, reason: null })).toBe("other");
  });

  it("words each interest refusal of the API with a fixed sentence", () => {
    const code = (c: string) => ({ detail: { code: c, message: "server text" } });
    expect(interestRefusalOf(403, code("step_up_required"))).toBe("stepUp");
    expect(interestRefusalOf(403, code("role_required"))).toBe("role_required");
    expect(interestRefusalOf(403, code("org_not_e2"))).toBe("org_not_e2");
    expect(interestRefusalOf(403, code("org_unavailable"))).toBe("org_unavailable");
    expect(interestRefusalOf(403, code("mfa_enrolment_required"))).toBe("mfaSetup");
    expect(interestRefusalOf(409, code("engagement_exists"))).toBe("engagement_exists");
    expect(interestRefusalOf(422, code("invalid_contact_by"))).toBe("invalidContactBy");
    expect(interestRefusalOf(422, code("invalid_contact"))).toBe("invalidContact");
    expect(interestRefusalOf(404, code("not_found"))).toBe("proposal_unavailable");
    expect(interestRefusalOf(403, code("refused"))).toBe("generic");
    expect(interestRefusalOf(502, undefined)).toBe("generic");
  });

  it("has a sentence for every reason and refusal in both namespaces", () => {
    const reasons = en.scoutMatch.reason as Record<string, string>;
    for (const key of ["org_not_e2", "org_unavailable", "role_required", "engagement_exists", "proposal_unavailable", "other"]) {
      expect(reasons[key], key).toBeTruthy();
    }
    const refusals = en.expressInterest.refusal as Record<string, string>;
    for (const key of [
      "role_required",
      "org_not_e2",
      "org_unavailable",
      "engagement_exists",
      "proposal_unavailable",
      "invalidContactBy",
      "invalidContact",
      "mfaSetup",
      "network",
      "generic",
    ]) {
      expect(refusals[key], key).toBeTruthy();
    }
    const scoutRefusals = en.scoutForm.refusal as Record<string, string>;
    for (const key of [
      "planLimit",
      "unknownNiche",
      "unknownCounty",
      "invalidRecipients",
      "invalid",
      "forbidden",
      "mfaSetup",
      "mfaCode",
      "notFound",
      "network",
      "generic",
    ]) {
      expect(scoutRefusals[key], key).toBeTruthy();
    }
  });
});

describe("an edited scout's stale choices", () => {
  const offered = { niches: new Set([NICHE]), counties: new Set(["KE-47"]), recipients: new Set([REVIEWER]) };
  const base = { ...draftOf(undefined, PLAN), niches: [NICHE], counties: ["KE-47"], recipients: [REVIEWER] };

  it("are dropped, and said to be", () => {
    const stale = { ...base, niches: [NICHE, "gone"], counties: ["KE-47", "KE-99"], recipients: ["left", REVIEWER] };
    expect(pruneDraft(stale, offered)).toEqual({ draft: base, dropped: true });
  });

  it("leave a current draft as it is", () => {
    expect(pruneDraft(base, offered)).toEqual({ draft: base, dropped: false });
  });

  it("keep the saved recipients when the reviewers are unknown (a failed read is not \"no reviewers\")", () => {
    const stale = { ...base, niches: [NICHE, "gone"], recipients: [REVIEWER, "someone"] };
    expect(pruneDraft(stale, { ...offered, recipients: null })).toEqual({
      draft: { ...base, recipients: [REVIEWER, "someone"] },
      dropped: true,
    });
    expect(pruneDraft(base, { ...offered, recipients: null })).toEqual({ draft: base, dropped: false });
  });
});

describe("the plan that has a schedule", () => {
  const plan = (code: string, frequencies: string[], upgrade_to: string | null, purchasable = true) => ({
    code,
    purchasable,
    upgrade_to,
    limits: { scout_frequencies: frequencies },
  });
  const PLANS = [
    plan("org_claimed", ["weekly"], "org_starter", false),
    plan("org_starter", ["weekly"], "org_growth"),
    plan("org_growth", ["daily", "weekly", "on_new"], "org_enterprise"),
    plan("org_enterprise", ["daily", "weekly", "on_new"], null, false),
  ];

  it("is the first up the ladder that sells it", () => {
    expect(planFor(PLANS, "org_claimed", "on_new")).toBe("org_growth");
    expect(planFor(PLANS, "org_starter", "daily")).toBe("org_growth");
  });

  it("falls back to the first plan that sells it, else none", () => {
    expect(planFor(PLANS, "unknown", "on_new")).toBe("org_growth");
    expect(planFor(PLANS.map((p) => ({ ...p, purchasable: false })), "org_claimed", "on_new")).toBeNull();
    const loop = [plan("a", ["weekly"], "b"), plan("b", ["weekly"], "a")];
    expect(planFor(loop, "a", "daily")).toBeNull();
  });
});

describe("a kept draft", () => {
  it("comes back only in a draft's shape", () => {
    const draft = { ...draftOf(undefined, PLAN), niches: [NICHE], include: "sacco" };
    expect(parseDraft(JSON.stringify(draft))).toEqual(draft);
    expect(parseDraft(null)).toBeNull();
    expect(parseDraft("{not json")).toBeNull();
    expect(parseDraft(JSON.stringify({ ...draft, frequency: "hourly" }))).toBeNull();
    expect(parseDraft(JSON.stringify({ ...draft, language: "fr" }))).toBeNull();
    expect(parseDraft(JSON.stringify({ ...draft, maturity: ["ancient"] }))).toBeNull();
    expect(parseDraft(JSON.stringify({ ...draft, niches: [1] }))).toBeNull();
    expect(parseDraft(JSON.stringify({ ...draft, minFit: 60 }))).toBeNull();
  });
});
