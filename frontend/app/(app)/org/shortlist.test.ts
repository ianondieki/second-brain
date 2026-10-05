import { describe, expect, it } from "vitest";

import type { Membership } from "./membership";
import {
  compareAction,
  compareProblem,
  editsShortlist,
  parseCompareIds,
  shortlistHref,
  shortlistProblem,
} from "./shortlist";

// REQ-REPO-02 (P21 track B): who may change the shortlist, the compare page's ids and the fixed sentences.

const A = "01a10b26-6c6d-72f4-b780-bc3566431999";
const B = "01a10b26-6be1-7063-8349-cb4c580ce388";
const C = "01a10b26-9998-7127-ae29-77e53da2a85e";
const D = "01a10b26-9998-7127-ae29-77e53da2a85f";
const E = "01a10b26-9998-7127-ae29-77e53da2a860";
const one: Membership[] = [{ org_id: "o1", org_name: "Telco A", roles: ["reviewer"] }];
const two: Membership[] = [...one, { org_id: "o2", org_name: "SACCO B", roles: ["viewer"] }];

describe("the shortlist's rules", () => {
  it("lets reviewers, signatories and admins change it, not an owner or viewer alone (P21 B1)", () => {
    for (const role of ["reviewer", "signatory", "admin"] as const) expect(editsShortlist({ roles: [role] })).toBe(true);
    expect(editsShortlist({ roles: ["owner", "viewer"] })).toBe(false);
    expect(editsShortlist({ roles: [] })).toBe(false);
  });

  it("links the Shortlist and Compare, naming the organisation only for members of several", () => {
    expect(shortlistHref(one, "o1")).toBe("/org/inbox/shortlist");
    expect(shortlistHref(two, "o2", "abc")).toBe("/org/inbox/shortlist?org=o2&cursor=abc");
    expect(compareAction(one, "o1")).toBe("/org/inbox/shortlist/compare");
    expect(compareAction(two, "o2")).toBe("/org/inbox/shortlist/compare?org=o2");
  });

  it("reads 2 to 4 distinct ids, comma-separated or repeated, in order (P21 B4)", () => {
    expect(parseCompareIds(`${A},${B}`)).toEqual({ kind: "ok", ids: [A, B] });
    expect(parseCompareIds([A, `${B},${C}`])).toEqual({ kind: "ok", ids: [A, B, C] });
    expect(parseCompareIds(`${A},${A.toUpperCase()},${B}`)).toEqual({ kind: "ok", ids: [A, B] });
    expect(parseCompareIds(`${A},not-an-id`)).toEqual({ kind: "count", ids: [A] });
    expect(parseCompareIds([A, B, C, D, E])).toEqual({ kind: "count", ids: [A, B, C, D, E] });
    expect(parseCompareIds(undefined)).toEqual({ kind: "count", ids: [] });
  });

  it("words each refusal of a change and of compare", () => {
    expect(shortlistProblem(0, undefined)).toBe("network");
    expect(shortlistProblem(401, { detail: { code: "mfa_required" } })).toBe("code");
    expect(shortlistProblem(401, { detail: { code: "not_authenticated" } })).toBe("signedOut");
    expect(shortlistProblem(401, undefined)).toBe("signedOut");
    expect(shortlistProblem(403, { detail: { code: "role_not_permitted" } })).toBe("role");
    expect(shortlistProblem(404, undefined)).toBe("gone");
    expect(shortlistProblem(500, undefined)).toBe("failed");
    expect(compareProblem({ detail: { code: "not_shortlisted" } })).toBe("notShortlisted");
    expect(compareProblem({ detail: { code: "compare_count" } })).toBe("count");
    expect(compareProblem({ detail: { code: "compare_repeated" } })).toBe("count");
  });
});
