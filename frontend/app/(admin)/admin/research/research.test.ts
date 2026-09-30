import { describe, expect, it } from "vitest";

import {
  excerptsByNiche,
  nicheLabel,
  publishReason,
  refusalKey,
  refusalOf,
  reviewHref,
  runNiches,
  runOutcome,
  type AdminNiche,
  type Excerpt,
} from "./research";

const niche = (slug: string, label: string): AdminNiche => ({
  id: `id-${slug}`,
  slug,
  label,
  name: label,
  parent_slug: null,
  isic_code: null,
  active: true,
  sort_order: 0,
});
const NICHES = [niche("agriculture", "Agriculture"), niche("health", "Health"), niche("microfinance-saccos", "SACCOs")];

const excerpt = (id: string, nicheSlug: string, published: string, country = "KE"): Excerpt => ({
  id,
  niche: nicheSlug,
  country,
  url: `https://example.go.ke/${id}`,
  publisher: "Publisher",
  source_type: "news",
  official: false,
  published_date: published,
  retrieved_at: "2026-09-29",
  quote: "A quote.",
  topic: "A topic",
  freshness: "fresh",
});

describe("runNiches", () => {
  it("offers each niche with a saved Kenyan excerpt once, by label", () => {
    const excerpts = [
      excerpt("a", "health", "2026-01-01"),
      excerpt("b", "agriculture", "2026-01-01"),
      excerpt("c", "health", "2026-02-01"),
      excerpt("d", "microfinance-saccos", "2026-01-01", "UG"),
      excerpt("e", "telecoms-x", "2026-01-01"),
    ];
    expect(runNiches(excerpts, NICHES)).toEqual([
      { slug: "agriculture", label: "Agriculture" },
      { slug: "health", label: "Health" },
      { slug: "telecoms-x", label: "telecoms-x" },
    ]);
    expect(runNiches([], NICHES)).toEqual([]);
  });

  it("names a niche by its label, else its slug", () => {
    expect(nicheLabel("health", NICHES)).toBe("Health");
    expect(nicheLabel("other", NICHES)).toBe("other");
    expect(nicheLabel(null, NICHES)).toBeNull();
  });

  it("groups excerpts by niche, newest first", () => {
    const excerpts = [
      excerpt("a", "health", "2026-01-01"),
      excerpt("c", "health", "2026-02-01"),
      excerpt("b", "agriculture", "2025-12-01"),
    ];
    const groups = excerptsByNiche(excerpts, runNiches(excerpts, NICHES));
    expect(groups.map((g) => [g.slug, g.excerpts.map((e) => e.id)])).toEqual([
      ["agriculture", ["b"]],
      ["health", ["c", "a"]],
    ]);
  });
});

describe("runOutcome", () => {
  const run = { status: "completed", stop_reason: null, demo_fallback: false, candidates: 0, discarded: 0 } as const;

  it("says a finished run's cards, or why it made none", () => {
    expect(runOutcome({ ...run, candidates: 2, discarded: 1 })).toEqual({ key: "cards", count: 2, total: 1 });
    expect(runOutcome({ ...run, discarded: 3 })).toEqual({ key: "noCard" });
    expect(runOutcome({ ...run, demo_fallback: true })).toEqual({ key: "demoFallback" });
  });

  it("names each known stop reason and folds the rest", () => {
    for (const reason of ["stale", "not_enough_excerpts", "search_or_fetch_cap", "input_token_cap", "injection_suspected"]) {
      expect(runOutcome({ ...run, status: "stopped", stop_reason: reason })).toEqual({ key: `stop.${reason}` });
    }
    expect(runOutcome({ ...run, status: "stopped", stop_reason: "something_new" })).toEqual({ key: "stop.other" });
    expect(runOutcome({ ...run, status: "stopped", stop_reason: null })).toEqual({ key: "stop.other" });
  });

  it("never shows a failed run's error code", () => {
    expect(runOutcome({ ...run, status: "failed", stop_reason: "llm_unavailable" })).toEqual({ key: "failed" });
    expect(runOutcome({ ...run, status: "running" })).toEqual({ key: "going" });
  });
});

const body = (code: string, message = "Server wording that is never shown.") => ({ detail: { code, message } });

describe("refusals", () => {
  it("reads the publish-check reason only from the API's exact sentence", () => {
    expect(publishReason(body("publish_check_failed", "This card cannot be published: non_latin_text."))).toBe(
      "non_latin_text",
    );
    expect(publishReason(body("publish_check_failed", "This card cannot be published: sources_archived."))).toBe(
      "sources_archived",
    );
    expect(publishReason(body("publish_check_failed", "This card cannot be published: control_character."))).toBe(
      "control_character",
    );
    expect(
      publishReason(body("publish_check_failed", "This card cannot be published: needs_official_or_two_publishers.")),
    ).toBe("needs_official_or_two_publishers");
    // Unknown reasons, other shapes and junk fall back to the general sentence.
    expect(publishReason(body("publish_check_failed", "This card cannot be published: brand_new_check."))).toBe("other");
    expect(publishReason(body("publish_check_failed", "Cannot publish: non_latin_text."))).toBe("other");
    expect(publishReason(body("publish_check_failed", "This card cannot be published: <b>x</b>."))).toBe("other");
    expect(publishReason("not json")).toBe("other");
    expect(publishReason(undefined)).toBe("other");
  });

  it("maps every refusal to a fixed sentence key", () => {
    const publish = refusalOf(409, body("publish_check_failed", "This card cannot be published: unsupported_number."));
    expect(publish).toEqual({ kind: "publish", reason: "unsupported_number" });
    expect(refusalKey(publish as Exclude<typeof publish, { kind: "stepUp" }>)).toBe("publish.unsupported_number");
    expect(refusalOf(409, body("checklist_required"))).toEqual({ kind: "refusal", code: "checklist_required" });
    expect(refusalOf(409, body("already_decided"))).toEqual({ kind: "refusal", code: "already_decided" });
    expect(refusalOf(409, body("run_in_progress"))).toEqual({ kind: "refusal", code: "run_in_progress" });
    expect(refusalOf(422, body("no_saved_excerpts"))).toEqual({ kind: "refusal", code: "no_saved_excerpts" });
    expect(refusalOf(422, body("unknown_niche"))).toEqual({ kind: "refusal", code: "unknown_niche" });
    expect(refusalOf(403, body("forbidden"))).toEqual({ kind: "refusal", code: "forbidden" });
    expect(refusalOf(403, body("step_up_required"))).toEqual({ kind: "stepUp" });
    expect(refusalKey({ kind: "refusal", code: "already_decided" })).toBe("refusal.already_decided");
  });

  it("never confirms existence and never passes an unknown code through", () => {
    expect(refusalOf(404, body("step_up_required"))).toEqual({ kind: "refusal", code: "not_found" });
    expect(refusalOf(409, body("brand_new_code"))).toEqual({ kind: "refusal", code: "generic" });
    expect(refusalOf(500, "Internal Server Error")).toEqual({ kind: "refusal", code: "generic" });
    expect(refusalOf(422, { detail: [{ loc: ["body", "niche"], msg: "bad", type: "x" }] })).toEqual({
      kind: "refusal",
      code: "generic",
    });
  });

  it("links a candidate's review page by its id", () => {
    expect(reviewHref("01a0f015-0feb-76bd-8eec-21b72f9f10e8")).toBe(
      "/admin/research/candidates/01a0f015-0feb-76bd-8eec-21b72f9f10e8",
    );
  });
});
