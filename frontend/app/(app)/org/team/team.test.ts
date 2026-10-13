import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import { loginHref } from "@/lib/return-path";

import { teamCalls, teamRefusal } from "./calls";
import {
  grantableRoles,
  manages,
  mayRemove,
  nicheDefaultsBody,
  nicheRows,
  reviewerChoices,
  roleWords,
  splitRoles,
  TEAM_SIGN_IN,
  type TeamMember,
} from "./team";

// REQ-TEN-02 (P28 track C): who may change what on the Team page, the roles as at most two chips, the niche rows the
// defaults form shows, and each write's request and refusal by the API's code (never its words).

const ORG = "0199c000-0000-7000-8000-0000000000a1";
const member = (user_id: string, roles: TeamMember["roles"], name = "Someone"): TeamMember => ({
  user_id,
  name,
  email: null,
  roles,
  joined_at: "2026-10-01T08:00:00Z",
});

describe("who may change the team", () => {
  it("lets owners and admins manage; role changes and the protected roles are an owner's", () => {
    expect(manages(["owner"])).toBe(true);
    expect(manages(["admin"])).toBe(true);
    expect(manages(["reviewer", "signatory", "finance", "viewer"])).toBe(false);
    expect(grantableRoles(["owner"])).toEqual(["owner", "admin", "signatory", "reviewer", "finance", "viewer"]);
    expect(grantableRoles(["admin"])).toEqual(["admin", "reviewer", "finance", "viewer"]);
    expect(mayRemove(["admin"], member("a", ["signatory"]))).toBe(false);
    expect(mayRemove(["admin"], member("a", ["owner", "admin"]))).toBe(false);
    expect(mayRemove(["admin"], member("a", ["reviewer"]))).toBe(true);
    expect(mayRemove(["owner"], member("a", ["owner"]))).toBe(true);
    expect(mayRemove(["reviewer"], member("a", ["viewer"]))).toBe(false);
  });

  it("offers reviewers, signatories and admins as a niche's default, never an owner, finance or viewer alone", () => {
    const people = [
      member("o", ["owner"]),
      member("a", ["owner", "admin"]),
      member("s", ["signatory"]),
      member("r", ["reviewer"]),
      member("f", ["finance"]),
      member("v", ["viewer"]),
    ];
    expect(reviewerChoices(people).map((m) => m.user_id)).toEqual(["a", "s", "r"]);
  });
});

describe("roles on a row", () => {
  it("shows the two most powerful as chips and names the rest (docs/spec/07 item 2: at most two chips)", () => {
    expect(splitRoles(["viewer", "owner"])).toEqual({ chips: ["owner", "viewer"], rest: [] });
    expect(splitRoles(["finance", "reviewer", "admin", "owner"])).toEqual({
      chips: ["owner", "admin"],
      rest: ["reviewer", "finance"],
    });
  });

  it("words roles as a list in the page's language", () => {
    const label = (role: string) => role.charAt(0).toUpperCase() + role.slice(1);
    expect(roleWords(["finance", "reviewer"], label, "en")).toBe("reviewer and finance");
    expect(roleWords(["viewer", "admin", "signatory"], label, "en")).toBe("admin, signatory, and viewer");
  });
});

describe("sign in again", () => {
  it("is lib/return-path's address for the Team page", () => {
    expect(TEAM_SIGN_IN).toBe(loginHref("/org/team"));
  });
});

describe("the niche defaults", () => {
  it("lists the organisation's niches with their defaults, then any default no longer on its card", () => {
    const rows = nicheRows(
      [
        { slug: "telecom", label: "ICT › Networks & Telecommunications" },
        { slug: "fintech", label: "Financial services › Payments" },
      ],
      [
        { niche_slug: "fintech", niche_name: "Payments", user_id: "r", name: "Rita" },
        { niche_slug: "dairy", niche_name: "Agriculture › Dairy", user_id: "s", name: "Peter" },
      ],
    );
    expect(rows).toEqual([
      { slug: "telecom", name: "ICT › Networks & Telecommunications", userId: null },
      { slug: "fintech", name: "Financial services › Payments", userId: "r" },
      { slug: "dairy", name: "Agriculture › Dairy", userId: "s" },
    ]);
  });

  it("sends the whole set, leaving out the niches set to nobody", () => {
    expect(nicheDefaultsBody({ telecom: "", fintech: "r", dairy: "s" })).toEqual({
      items: [
        { niche_slug: "fintech", user_id: "r" },
        { niche_slug: "dairy", user_id: "s" },
      ],
    });
  });
});

/** A client that answers every call with `answer` and records what was asked. */
function client(answer: { status: number; data?: unknown; error?: unknown } | Error) {
  const calls: Array<{ method: string; path: string; options: unknown }> = [];
  const respond = (method: string) =>
    vi.fn(async (path: string, options: unknown) => {
      calls.push({ method, path, options });
      if (answer instanceof Error) throw answer;
      return {
        data: answer.status < 300 ? (answer.data ?? undefined) : undefined,
        error: answer.error,
        response: new Response(null, { status: answer.status === 204 ? 204 : answer.status }),
      };
    });
  const api = { GET: respond("GET"), POST: respond("POST"), PUT: respond("PUT"), DELETE: respond("DELETE") };
  return { api: api as unknown as ApiClient, calls };
}

describe("the writes", () => {
  it("send each change to its own address with its body", async () => {
    const { api, calls } = client({ status: 200, data: {} });
    const team = teamCalls(ORG, api);
    await team.invite("wanjiru@telco-a.example", ["reviewer"]);
    await team.resend("inv-1");
    await team.revoke("inv-1");
    await team.remove("user-1");
    await team.setRoles("user-1", ["admin", "reviewer"]);
    await team.setNicheDefaults([{ niche_slug: "telecom", user_id: "user-1" }]);
    await team.setEscalationContact(null);
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/api/orgs/{org_id}/invitations",
        options: { params: { path: { org_id: ORG } }, body: { email: "wanjiru@telco-a.example", roles: ["reviewer"] } },
      },
      {
        method: "POST",
        path: "/api/orgs/{org_id}/invitations/{invitation_id}/resend",
        options: { params: { path: { org_id: ORG, invitation_id: "inv-1" } } },
      },
      {
        method: "DELETE",
        path: "/api/orgs/{org_id}/invitations/{invitation_id}",
        options: { params: { path: { org_id: ORG, invitation_id: "inv-1" } } },
      },
      {
        method: "DELETE",
        path: "/api/orgs/{org_id}/members/{user_id}",
        options: { params: { path: { org_id: ORG, user_id: "user-1" } } },
      },
      {
        method: "PUT",
        path: "/api/orgs/{org_id}/members/{user_id}/roles",
        options: { params: { path: { org_id: ORG, user_id: "user-1" } }, body: { roles: ["admin", "reviewer"] } },
      },
      {
        method: "PUT",
        path: "/api/orgs/{org_id}/niche-defaults",
        options: { params: { path: { org_id: ORG } }, body: { items: [{ niche_slug: "telecom", user_id: "user-1" }] } },
      },
      {
        method: "PUT",
        path: "/api/orgs/{org_id}/escalation-contact",
        options: { params: { path: { org_id: ORG } }, body: { user_id: null } },
      },
    ]);
  });

  it("settle a 204 as done", async () => {
    const { api } = client({ status: 204 });
    expect(await teamCalls(ORG, api).revoke("inv-1")).toEqual({ ok: true, value: null });
  });

  it.each([
    [403, "step_up_required", "stepUp"],
    [422, "invalid_email", "invalid_email"],
    [409, "already_member", "already_member"],
    [409, "already_invited", "already_invited"],
    [403, "protected_role", "protected_role"],
    [403, "org_not_verified", "org_not_verified"],
    [409, "invitation_closed", "invitation_closed"],
    [403, "protected_member", "protected_member"],
    [409, "last_owner", "last_owner"],
    [422, "unknown_niche", "unknown_niche"],
    [422, "duplicate_niche", "unknown_niche"],
    [422, "invalid_default_reviewer", "invalid_default_reviewer"],
    [422, "invalid_member", "invalid_member"],
    [429, "rate_limited", "rate_limited"],
    [403, "public_demo_locked", "public_demo_locked"],
    [402, "plan_limit", "plan_limit"],
    [404, "not_found", "notFound"],
    [403, "role_not_permitted", "notAllowed"],
    [401, "unauthenticated", "signedOut"],
    [409, "conflict", "conflict"],
    [500, undefined, "generic"],
  ])("name a %i %s as %s", (status, code, refusal) => {
    expect(teamRefusal(status, code ? { detail: { code, message: "server words" } } : undefined)).toBe(refusal);
  });

  it("read a request-validation error on the address as an invalid email", () => {
    expect(teamRefusal(422, { detail: [{ loc: ["body", "email"], msg: "x", type: "value_error" }] })).toBe(
      "invalid_email",
    );
  });

  it("carry the cap of open invitations and the plan with more seats", async () => {
    const full = client({ status: 409, error: { detail: { code: "too_many_invitations", message: "m", limit: 20 } } });
    expect(await teamCalls(ORG, full.api).invite("a@b.example", ["viewer"])).toEqual({
      ok: false,
      refusal: "too_many_invitations",
      limit: 20,
    });
    const seats = client({
      status: 402,
      error: { detail: { code: "plan_limit", message: "m", limit: 3, upgrade: { plan: "org_growth", url: "/x" } } },
    });
    expect(await teamCalls(ORG, seats.api).invite("a@b.example", ["viewer"])).toEqual({
      ok: false,
      refusal: "plan_limit",
      limit: 3,
      upgrade: "org_growth",
    });
  });

  it("carry the API's Retry-After on a 429 (seconds or a date)", async () => {
    const answer = (retry: string | null) => {
      const headers = new Headers(retry ? { "Retry-After": retry } : {});
      const api = {
        POST: vi.fn(async () => ({
          error: { detail: { code: "rate_limited", message: "m" } },
          response: new Response(null, { status: 429, headers }),
        })),
      } as unknown as ApiClient;
      return teamCalls(ORG, api).invite("a@b.example", ["viewer"]);
    };
    expect(await answer("300")).toEqual({ ok: false, refusal: "rate_limited", retryAfter: 300 });
    expect(await answer(null)).toEqual({ ok: false, refusal: "rate_limited" });
  });

  it("say no connection when the request never reached the API", async () => {
    const { api } = client(new TypeError("Failed to fetch"));
    expect(await teamCalls(ORG, api).setEscalationContact("u")).toEqual({ ok: false, refusal: "network" });
  });
});
