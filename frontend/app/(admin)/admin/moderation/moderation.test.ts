import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import {
  caseHref,
  caseKind,
  caseReasons,
  caseTitle,
  fieldKey,
  moderationView,
  outcome,
  REASONS,
  reasonTone,
  FIELDS,
  refusalNext,
  refusalOf,
  viewHref,
  visibility,
} from "./moderation";

const error = (code: string, message = "The API's own words.") => ({ detail: { code, message } });

describe("moderation queue views (REQ-MOD-01)", () => {
  it("opens the open cases unless the decided ones are asked for", () => {
    expect(moderationView(undefined)).toBe("open");
    expect(moderationView("decided")).toBe("decided");
    expect(moderationView("DECIDED")).toBe("open");
    expect(moderationView("anything")).toBe("open");
    expect(viewHref("open")).toBe("/admin/moderation");
    expect(viewHref("decided")).toBe("/admin/moderation?view=decided");
    expect(caseHref("01a0ee62-f783-733e-9321-9f34ec389ac2")).toBe(
      "/admin/moderation/cases/01a0ee62-f783-733e-9321-9f34ec389ac2",
    );
  });
});

describe("what a case is about", () => {
  it("names the subjects the queue knows, and nothing else", () => {
    expect(caseKind("proposal")).toBe("proposal");
    expect(caseKind("problem")).toBe("problem");
    expect(caseKind("org_claim")).toBe("org_claim");
    expect(caseKind("message")).toBe("message"); // a party's report of an engagement message (REQ-ENG-11)
    expect(caseKind("comment")).toBe("other");
  });

  it("reads the title from the current text first, then the preview", () => {
    const fields = [{ name: "summary", text: "A summary" }];
    expect(caseTitle({ fields: [{ name: "title", text: " Now " }], preview: { title: "Then", text: null } })).toBe(
      "Now",
    );
    expect(caseTitle({ fields, preview: { title: "Then", text: null } })).toBe("Then");
    expect(caseTitle({ fields, preview: { title: "  ", text: null } })).toBeNull();
  });

  it("gives every reason a fixed sentence, unknown ones one 'other' line", () => {
    expect(caseReasons(["names_real_org_negative", "spam", "made_up", "also_made_up", "spam"])).toEqual([
      "names_real_org_negative",
      "spam",
      "other",
    ]);
    const sentences = en.adminModeration.reason as Record<string, string>;
    for (const reason of [...REASONS, "other"]) expect(sentences[reason], reason).toBeTruthy();
  });

  it("reads routine reasons as information and the rest as flags", () => {
    expect(reasonTone("new_developer_problem")).toBe("info");
    expect(reasonTone("new_version_of_moderated_proposal")).toBe("info");
    expect(reasonTone("names_real_org_negative")).toBe("flag");
    expect(reasonTone("security_vulnerability")).toBe("flag");
    expect(reasonTone("other")).toBe("flag");
  });

  it("labels the Tier-1 fields and nothing else", () => {
    expect(fieldKey("problem_statement")).toBe("problem_statement");
    expect(fieldKey("approach")).toBe("other"); // a Tier-2 name never gets its own label
    const labels = en.adminModeration.field as Record<string, string>;
    for (const field of [...FIELDS, "other"]) expect(labels[field], field).toBeTruthy();
  });

  it("says whether the subject can be seen outside the queue", () => {
    const at = (subject_type: string, subject_state: "clear" | "held" | "rejected" | null, blocked = null) =>
      visibility({ subject_type, subject_state, blocked });
    expect(at("proposal", "held")).toBe("hidden");
    expect(at("problem", "clear")).toBe("public");
    expect(at("proposal", "rejected")).toBe("rejected");
    expect(at("proposal", null)).toBe("gone");
    expect(visibility({ subject_type: "problem", subject_state: "clear", blocked: "subject_gone" })).toBe("gone");
    expect(at("org_claim", null)).toBeNull();
  });

  it("knows a decided case's outcome", () => {
    expect(outcome({ status: "approved" })).toBe("approved");
    expect(outcome({ status: "rejected" })).toBe("rejected");
    expect(outcome({ status: "held" })).toBeNull();
    expect(outcome({ status: "escalated" })).toBeNull();
  });
});

describe("decision refusals", () => {
  it("maps each answer to a fixed sentence, never the API's message", () => {
    expect(refusalOf(403, error("step_up_required"))).toEqual({ kind: "stepUp" });
    expect(refusalOf(409, error("case_changed"))).toEqual({ kind: "changed" });
    expect(refusalOf(409, error("already_decided"))).toEqual({ kind: "refusal", code: "already_decided" });
    expect(refusalOf(409, error("cannot_approve_vulnerability"))).toEqual({
      kind: "refusal",
      code: "cannot_approve_vulnerability",
    });
    expect(refusalOf(409, error("unsupported_subject"))).toEqual({ kind: "refusal", code: "unsupported_subject" });
    expect(refusalOf(403, error("own_content"))).toEqual({ kind: "refusal", code: "own_content" });
    expect(refusalOf(409, error("subject_gone"))).toEqual({ kind: "refusal", code: "subject_gone" });
    expect(refusalOf(403, error("forbidden"))).toEqual({ kind: "refusal", code: "forbidden" });
    expect(refusalOf(403, undefined)).toEqual({ kind: "refusal", code: "forbidden" });
    expect(refusalOf(422, { detail: [{ loc: ["body", "decision"] }] })).toEqual({ kind: "refusal", code: "generic" });
    expect(refusalOf(500, error("boom"))).toEqual({ kind: "refusal", code: "generic" });
  });

  it("treats every 404 as a case that is gone, whatever its body says", () => {
    expect(refusalOf(404, error("step_up_required"))).toEqual({ kind: "refusal", code: "not_found" });
    expect(refusalOf(404, undefined)).toEqual({ kind: "refusal", code: "not_found" });
  });

  it("leaves only the way back, only Reject, or the same choices", () => {
    expect(refusalNext("already_decided")).toBe("back");
    expect(refusalNext("not_found")).toBe("back");
    expect(refusalNext("own_content")).toBe("back");
    expect(refusalNext("subject_gone")).toBe("back");
    expect(refusalNext("unsupported_subject")).toBe("back");
    expect(refusalNext("forbidden")).toBe("back");
    expect(refusalNext("cannot_approve_vulnerability")).toBe("rejectOnly");
    expect(refusalNext("generic")).toBeNull();
  });

  it("has a sentence for every refusal and every block", () => {
    const refusal = en.adminModeration.refusal as Record<string, string>;
    for (const code of [
      "already_decided",
      "not_found",
      "own_content",
      "subject_gone",
      "cannot_approve_vulnerability",
      "unsupported_subject",
      "forbidden",
      "generic",
    ]) {
      expect(refusal[code], code).toBeTruthy();
    }
    const blocked = en.adminModeration.blocked as Record<string, string>;
    for (const code of [
      "already_decided",
      "unsupported_subject",
      "subject_gone",
      "own_content",
      "cannot_approve_vulnerability",
    ]) {
      expect(blocked[code], code).toBeTruthy();
    }
  });
});
