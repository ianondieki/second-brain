import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";

import { pitch, withdrawTag } from "./calls";
import {
  canWithdraw,
  heldKey,
  MAX_BATCH,
  orgKey,
  parsePickerQuery,
  pickerApiQuery,
  pitchesLeft,
  pitchHref,
  selectionMax,
  tagState,
} from "./picker";
import { pitchRefusal, withdrawRefusal } from "./refusals";

// REQ-PROP-03 (F2 picker), REQ-DIR-04 (held tags): the picker's URL, the plan cap as "N of M left", what each tag
// reads as, and every refusal of a Pitch or a withdrawal mapped to one plainly worded problem.

const PROPOSAL = "0199a000-0000-7000-8000-0000000000aa";
const ORG_A = "0199a000-0000-7000-8000-00000000000a";
const ORG_B = "0199a000-0000-7000-8000-00000000000b";

function error(code: string, extra: Record<string, unknown> = {}) {
  return { detail: { code, message: "The API's own words, never shown", ...extra } };
}

describe("the picker's URL", () => {
  it("keeps the search, niche, page and chosen organisations, and drops anything malformed", () => {
    expect(
      parsePickerQuery({
        q: "  maji  ",
        niche: "agri-dairy",
        cursor: "abc",
        sel: [ORG_A, "not-a-uuid", ORG_A.toUpperCase(), ORG_B],
      }),
    ).toEqual({ q: "maji", niche: "agri-dairy", cursor: "abc", selected: [ORG_A, ORG_B] });
    expect(parsePickerQuery({ q: "   ", niche: "Not A Slug", cursor: "x".repeat(2001) })).toEqual({ selected: [] });
  });

  it("keeps at most one batch of chosen organisations", () => {
    const many = Array.from({ length: 25 }, (_, i) => `0199a000-0000-7000-8000-${String(i).padStart(12, "0")}`);
    expect(parsePickerQuery({ sel: many }).selected).toHaveLength(MAX_BATCH);
  });

  it("cuts a long search by code point, never inside an emoji", () => {
    const q = parsePickerQuery({ q: "🐄".repeat(120) }).q!;
    expect(Array.from(q)).toHaveLength(100);
    expect(() => encodeURIComponent(q)).not.toThrow();
  });

  it("links back to the same search with the choices", () => {
    expect(pitchHref(PROPOSAL, { q: "dairy co-op", selected: [ORG_A, ORG_B] })).toBe(
      `/dev/ideas/${PROPOSAL}/pitch?q=dairy+co-op&sel=${ORG_A}&sel=${ORG_B}`,
    );
    expect(pitchHref(PROPOSAL)).toBe(`/dev/ideas/${PROPOSAL}/pitch`);
    expect(pickerApiQuery({ niche: "agri", selected: [ORG_A] })).toEqual({
      q: undefined,
      niche: ["agri"],
      cursor: undefined,
      limit: 30,
    });
  });
});

describe("an organisation's id", () => {
  it("is compared in one case everywhere (the URL, cards, refusals and choices go through orgKey)", () => {
    expect(orgKey(ORG_A.toUpperCase())).toBe(ORG_A);
    expect(orgKey(ORG_A)).toBe(ORG_A);
    expect(pitchRefusal(404, error("not_found", { org_ids: [ORG_B.toUpperCase(), 7] })).gone).toEqual([ORG_B]);
  });
});

describe("the plan cap", () => {
  it("reads as pitches left, never below zero", () => {
    expect(pitchesLeft({ used: 2, limit: 5, plan: "dev_free" })).toBe(3);
    expect(pitchesLeft({ used: 7, limit: 5, plan: "dev_free" })).toBe(0);
    expect(pitchesLeft({ used: 7, limit: null, plan: "dev_pro" })).toBeNull();
  });

  it("limits one Pitch to the batch size or what the plan has left, whichever is smaller", () => {
    expect(selectionMax({ used: 2, limit: 5, plan: "dev_free" })).toBe(3);
    expect(selectionMax({ used: 0, limit: 50, plan: "dev_pro" })).toBe(MAX_BATCH);
    expect(selectionMax({ used: 0, limit: null, plan: "dev_pro" })).toBe(MAX_BATCH);
    expect(selectionMax({ used: 5, limit: 5, plan: "dev_free" })).toBe(0);
  });
});

describe("a tag", () => {
  it.each([
    [{ status: "delivered", open: true }, "sent", false],
    [{ status: "held_unclaimed", open: true }, "saved", true],
    [{ status: "held_pending_verification", open: true }, "saved", true],
    [{ status: "withdrawn", open: false }, "withdrawn", false],
    [{ status: "delivered", open: false }, "closed", false],
    [{ status: "expired", open: false }, "closed", false],
    [{ status: "released", open: false }, "closed", false],
  ] as const)("%o reads as %s (withdrawable here: %s)", (tag, state, withdrawable) => {
    expect(tagState(tag)).toBe(state);
    expect(canWithdraw(tag)).toBe(withdrawable);
  });

  it("carries the held sentence of its level", () => {
    expect(heldKey("held_unclaimed")).toBe("heldUnclaimed");
    expect(heldKey("held_pending_verification")).toBe("heldPending");
    expect(heldKey("delivered")).toBeNull();
  });
});

describe("a refused Pitch", () => {
  it.each([
    [0, undefined, "network"],
    [401, error("not_authenticated"), "signedOut"],
    [401, error("mfa_required"), "mfaRequired"],
    [429, error("rate_limited"), "rateLimited"],
    [503, error("unavailable"), "unavailable"],
    [403, error("d1_required"), "d1Required"],
    [404, error("not_found"), "notFound"],
    [404, error("not_found", { org_ids: [ORG_A] }), "orgsGone"],
    [409, error("proposal_not_public"), "notPublic"],
    [409, error("tag_conflict"), "changed"],
    [402, error("plan_limit"), "planLimitUnknown"],
    [422, { detail: [{ loc: ["body", "org_ids"], msg: "too long" }] }, "failed"],
    [500, undefined, "failed"],
  ] as const)("%s %o is %s", (status, body, problem) => {
    expect(pitchRefusal(status, body).problem).toBe(problem);
  });

  it("keeps the cap of a 402", () => {
    expect(pitchRefusal(402, error("plan_limit", { limit: 5, used: 4, limit_key: "tags_per_proposal" }))).toEqual({
      problem: "planLimit",
      conflicts: [],
      limit: 5,
      used: 4,
    });
  });

  it("keeps the next plan up of a 402 (REQ-BIL-08)", () => {
    const upgrade = { plan: "dev_pro_monthly", url: "/billing/upgrade?plan=dev_pro_monthly" };
    expect(pitchRefusal(402, error("plan_limit", { limit: 5, used: 5, upgrade })).upgrade).toBe("dev_pro_monthly");
    expect(pitchRefusal(402, error("plan_limit", { upgrade })).upgrade).toBe("dev_pro_monthly");
    expect(pitchRefusal(402, error("plan_limit", { limit: 5, used: 5, upgrade: null })).upgrade).toBeUndefined();
  });

  it("names each organisation of a 409 with its reason, in the order asked", () => {
    const refusal = pitchRefusal(
      409,
      error("tag_conflict", {
        conflicts: [
          { org_id: ORG_B.toUpperCase(), reason: "cooldown", message: "…" },
          { org_id: ORG_A, reason: "open_elsewhere", message: "…" },
          { org_id: ORG_A, reason: "a reason this screen does not know", message: "…" },
        ],
      }),
    );
    expect(refusal).toEqual({
      problem: "conflict",
      conflicts: [
        { orgId: ORG_B, reason: "cooldown" },
        { orgId: ORG_A, reason: "open_elsewhere" },
      ],
    });
  });
});

describe("a refused withdrawal", () => {
  it.each([
    [0, undefined, "network"],
    [401, error("not_authenticated"), "signedOut"],
    [404, error("not_found"), "notFound"],
    [409, error("tag_closed"), "closed"],
    [409, error("tag_delivered"), "delivered"],
    [500, undefined, "failed"],
  ] as const)("%s %o is %s", (status, body, problem) => {
    expect(withdrawRefusal(status, body)).toBe(problem);
  });
});

describe("the calls", () => {
  function client(answer: () => Promise<{ data?: unknown; error?: unknown; response: Response }>) {
    const POST = vi.fn(answer);
    return { client: { POST } as unknown as ApiClient, POST };
  }

  it("pitches the chosen organisations in one request", async () => {
    const result = { tags: [], sent_count: 1, saved_count: 1, email_sent: true, cap: { used: 2, limit: 5, plan: "p" } };
    const { client: fake, POST } = client(async () => ({ data: result, response: new Response(null, { status: 201 }) }));
    await expect(pitch(PROPOSAL, [ORG_A, ORG_B], fake)).resolves.toEqual({ ok: true, value: result });
    expect(POST).toHaveBeenCalledWith("/api/me/proposals/{proposal_id}/tags", {
      params: { path: { proposal_id: PROPOSAL } },
      body: { org_ids: [ORG_A, ORG_B] },
    });
  });

  it("settles a thrown fetch as a network problem", async () => {
    const { client: fake } = client(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(pitch(PROPOSAL, [ORG_A], fake)).resolves.toMatchObject({ ok: false, problem: "network" });
    await expect(withdrawTag(PROPOSAL, ORG_A, fake)).resolves.toEqual({ ok: false, problem: "network" });
  });

  it("withdraws one tag and words a refusal", async () => {
    const { client: fake, POST } = client(async () => ({
      error: error("tag_delivered"),
      response: new Response(null, { status: 409 }),
    }));
    await expect(withdrawTag(PROPOSAL, ORG_A, fake)).resolves.toEqual({ ok: false, problem: "delivered" });
    expect(POST).toHaveBeenCalledWith("/api/me/proposals/{proposal_id}/tags/{tag_id}/withdraw", {
      params: { path: { proposal_id: PROPOSAL, tag_id: ORG_A } },
    });
  });
});
