import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import { inboxHref, isUuid, orgQuery, pickMembership, proposalHref, type Membership } from "./membership";
import { ACTION_HREF, REFUSAL_ACTION, REFUSALS, refusalOf } from "./refusals";

const A: Membership = { org_id: "01a0ee62-0000-7000-8000-00000000000a", org_name: "Amani Foods", roles: ["reviewer"] };
const B: Membership = { org_id: "01a0ee62-0000-7000-8000-00000000000b", org_name: "Baraka Bank", roles: ["admin"] };
const PROPOSAL = "01a0ee62-f783-733e-9321-9f34ec389ac2";

describe("the organisation a screen acts for (org picker)", () => {
  it("is the first membership unless another one of the person's is asked for", () => {
    expect(pickMembership([A, B], undefined)).toBe(A);
    expect(pickMembership([A, B], B.org_id)).toBe(B);
    expect(pickMembership([A, B], B.org_id.toUpperCase())).toBe(B);
    expect(pickMembership([A, B], [B.org_id, A.org_id])).toBe(B);
  });

  it("never acts for an organisation the person is not a member of", () => {
    expect(pickMembership([A, B], "01a0ee62-0000-7000-8000-0000000000ff")).toBe(A);
    expect(pickMembership([A], "not-a-uuid")).toBe(A);
    expect(pickMembership([], A.org_id)).toBeNull();
  });

  it("names the organisation in links only when the person has several", () => {
    expect(orgQuery([A], A.org_id)).toBe("");
    expect(orgQuery([A, B], B.org_id)).toBe(`?org=${B.org_id}`);
    expect(inboxHref([A], A.org_id)).toBe("/org/inbox");
    expect(inboxHref([A, B], A.org_id, "abc_-")).toBe(`/org/inbox?org=${A.org_id}&cursor=abc_-`);
    expect(proposalHref([A], A.org_id, PROPOSAL)).toBe(`/org/inbox/${PROPOSAL}`);
    expect(proposalHref([A], A.org_id, PROPOSAL, { view: true })).toBe(`/org/inbox/${PROPOSAL}?view=full`);
    expect(proposalHref([A, B], B.org_id, PROPOSAL, { view: true })).toBe(
      `/org/inbox/${PROPOSAL}?org=${B.org_id}&view=full`,
    );
  });

  it("checks ids before they reach the API", () => {
    expect(isUuid(PROPOSAL)).toBe(true);
    expect(isUuid(undefined)).toBe(false);
    expect(isUuid("../auth/me")).toBe(false);
    expect(isUuid(`${PROPOSAL}/x`)).toBe(false);
  });
});

describe("refusals (REQ-REPO-01, REQ-SEC-01)", () => {
  const body = (code: string) => ({ detail: { code, message: "server wording, never shown" } });

  it("maps each code of the Tier-2 gate and predicate to its own refusal", () => {
    expect(refusalOf(401, body("mfa_required"))).toBe("mfa_required");
    expect(refusalOf(403, body("tier2_disabled"))).toBe("tier2_disabled");
    expect(refusalOf(403, body("grant_required"))).toBe("grant_required");
    expect(refusalOf(403, body("nda_required"))).toBe("nda_required");
    expect(refusalOf(409, body("nda_outdated"))).toBe("nda_outdated");
    expect(refusalOf(403, body("master_terms_required"))).toBe("master_terms_required");
    expect(refusalOf(403, body("org_not_e2"))).toBe("org_not_e2");
    expect(refusalOf(403, body("engagement_ended"))).toBe("engagement_ended");
    expect(refusalOf(403, body("step_up_required"))).toBe("step_up_required");
    expect(refusalOf(503, body("not_configured"))).toBe("not_configured");
  });

  it("answers every 404 as not found, whatever the body says", () => {
    expect(refusalOf(404, body("not_found"))).toBe("not_found");
    expect(refusalOf(404, body("grant_required"))).toBe("not_found");
    expect(refusalOf(404, undefined)).toBe("not_found");
  });

  it("treats unknown codes, validation errors and unreadable bodies as generic", () => {
    expect(refusalOf(403, body("something_new"))).toBe("generic");
    expect(refusalOf(422, { detail: [{ loc: ["body", "sha256"], msg: "bad", type: "value_error" }] })).toBe("generic");
    expect(refusalOf(500, "Internal Server Error")).toBe("generic");
    expect(refusalOf(403, undefined)).toBe("generic");
  });

  it("gives every refusal its own sentence and at most one action, with a label for each action", () => {
    const sentences = en.orgProposal.refusal as Record<string, string>;
    const actions = en.orgProposal.action as Record<string, string>;
    for (const refusal of [...REFUSALS, "generic" as const]) {
      expect(sentences[refusal], refusal).toBeTruthy();
      const action = REFUSAL_ACTION[refusal];
      if (action) expect(actions[action], `${refusal} → ${action}`).toBeTruthy();
    }
    // One sentence each: no refusal reuses another's wording.
    const texts = [...REFUSALS, "generic"].map((r) => sentences[r]);
    expect(new Set(texts).size).toBe(texts.length);
  });

  it("sends the second-factor refusals to the right step", () => {
    expect(REFUSAL_ACTION.mfa_required).toBe("enterCode");
    expect(ACTION_HREF.enterCode).toBe("/auth/mfa");
    expect(REFUSAL_ACTION.mfa_enrolment_required).toBe("turnOnMfa");
    expect(ACTION_HREF.turnOnMfa).toBe("/settings/security");
    expect(REFUSAL_ACTION.step_up_required).toBe("stepUp");
    expect(REFUSAL_ACTION.nda_outdated).toBe("newVersion");
    // Conditions only someone else can change offer no action of their own.
    for (const refusal of ["tier2_disabled", "org_not_e2", "master_terms_required", "role_not_permitted"] as const) {
      expect(REFUSAL_ACTION[refusal], refusal).toBeNull();
    }
  });
});
