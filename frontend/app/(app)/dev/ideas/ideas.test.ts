import { describe, expect, it, vi } from "vitest";

import { publish, saveDraft, searchProblems, uploadAttachment } from "./calls";
import { draftBody } from "./draft";
import {
  editHref,
  linksProblem,
  publishChecklist,
  wordCount,
  type EditorState,
  type Version,
} from "./ideas";
import { attachmentType, fileSizeParts } from "./files";
import { hasUnpublishedChanges, ideaStatus } from "./status";
import { parseStep } from "./routes";
import { EMPTY_STATE, stateFromVersion } from "./versions";
import { fieldIssues, saveRefusal } from "./outcomes";
import { publishRefusal, uploadRefusal } from "./refusals";

// REQ-PROP-01 (F2): the My ideas editor's logic. AC-REPO-4/a is the API's (422 cannot_publish); the screen shows the
// same checks before publishing and every refusal next to its field.

const PROBLEM = {
  id: "0199a000-0000-7000-8000-000000000101",
  title: "Farmers lose milk to spoilage",
  source: "developer" as const,
  label: "Developer-reported",
  niche: null,
  seeded_example: false,
  published_at: null,
};

const READY: EditorState = {
  ...EMPTY_STATE,
  title: "Cold chain for dairy co-ops",
  nicheId: "0199a000-0000-7000-8000-000000000001",
  maturity: "prototype",
  ask: "pilot",
  problemStatement: "Milk spoils before collection.",
  summary: "Solar chillers with shared scheduling.",
  problemMode: "pick",
  problems: [PROBLEM],
};

function version(overrides: Partial<Version> = {}): Version {
  return {
    id: "0199a000-0000-7000-8000-0000000000aa",
    version_no: 1,
    status: "draft",
    cert_id: null,
    registered_at: null,
    provenance: null,
    teaser: {
      title: "Cold chain",
      niche: { id: "n1", slug: "agri", label: "Agriculture › Dairy" },
      country: "KE",
      county_code: "KE-30",
      maturity: "idea",
      ask: "sale",
      problem_statement: "Spoilage",
      impact_claims: null,
      summary: "Chillers",
    },
    problems: [],
    new_problem: null,
    confidential: {
      approach: "Solar",
      architecture: null,
      pricing: null,
      notes: null,
      links: ["https://example.com/demo", "https://example.com/repo"],
      attachments: [],
    },
    ...overrides,
  };
}

describe("status", () => {
  it.each([
    ["draft", "clear", "draft"],
    ["published", "clear", "published"],
    ["published", "held", "held"],
    ["published", "rejected", "rejected"],
    ["hidden", "clear", "hidden"],
    ["archived", "held", "hidden"],
  ] as const)("%s + %s reads as %s", (status, moderation, expected) => {
    expect(ideaStatus(status, moderation)).toBe(expected);
  });

  it("flags saved changes on a published idea only", () => {
    expect(hasUnpublishedChanges({ status: "published", has_draft: true })).toBe(true);
    expect(hasUnpublishedChanges({ status: "draft", has_draft: true })).toBe(false);
    expect(hasUnpublishedChanges({ status: "published", has_draft: false })).toBe(false);
  });

  it("reads the step from the URL and builds edit links", () => {
    expect(parseStep("2")).toBe(2);
    expect(parseStep(["3"])).toBe(3);
    expect(parseStep("9")).toBe(1);
    expect(parseStep(undefined)).toBe(1);
    expect(editHref("abc")).toBe("/dev/ideas/abc/edit");
    expect(editHref("abc", 3)).toBe("/dev/ideas/abc/edit?step=3");
  });
});

describe("the editor's state", () => {
  it("loads a version into the fields", () => {
    const state = stateFromVersion(version());
    expect(state).toMatchObject({
      title: "Cold chain",
      nicheId: "n1",
      countyCode: "KE-30",
      maturity: "idea",
      approach: "Solar",
      links: "https://example.com/demo\nhttps://example.com/repo",
      problemMode: null, // nothing linked or described yet: the editor asks
    });
  });

  it("opens on 'Describe a new problem' when the draft has one and no linked problem", () => {
    const state = stateFromVersion(
      version({ new_problem: { title: "Late payments", statement: "Suppliers wait.", niche_id: null } }),
    );
    expect(state.problemMode).toBe("new");
    expect(state.newProblemTitle).toBe("Late payments");
  });

  it("leaves the problems alone until a way of naming them is chosen", () => {
    const { body } = draftBody({ ...READY, problemMode: null });
    expect(body).not.toHaveProperty("problem_ids");
    expect(body).not.toHaveProperty("new_problem");
    expect(publishChecklist({ ...READY, problemMode: null })).toEqual([{ field: "problems", code: "problem_required" }]);
  });

  it("sends every field, empty ones as null, and clears the problem not chosen", () => {
    const { body, held } = draftBody(READY);
    expect(held).toEqual([]);
    expect(body.teaser).toMatchObject({ title: READY.title, county_code: null, impact_claims: null });
    expect(body.problem_ids).toEqual([PROBLEM.id]);
    expect(body.new_problem).toBeNull();
    expect(body.confidential).toMatchObject({ approach: null, links: [] });

    const described = draftBody({
      ...READY,
      problemMode: "new",
      newProblemTitle: " Late payments ",
      newProblemStatement: "Suppliers wait.",
    });
    expect(described.body.problem_ids).toEqual([]);
    expect(described.body.new_problem).toEqual({
      title: "Late payments",
      statement: "Suppliers wait.",
      niche_id: READY.nicheId,
    });
  });

  it("holds back links that are not web addresses and a half-written new problem", () => {
    const plan = draftBody({ ...READY, links: "https://ok.example\nftp://files.example", problemMode: "new", newProblemTitle: "x" });
    expect(plan.held).toEqual(["links", "newProblem"]);
    expect(plan.body.confidential).not.toHaveProperty("links");
    expect(plan.body).not.toHaveProperty("new_problem");
  });

  it("checks links as the API does", () => {
    expect(linksProblem("")).toBeNull();
    expect(linksProblem("https://a.example\n\n http://b.example ")).toBeNull();
    expect(linksProblem("a.example")).toBe("notWeb");
    expect(linksProblem("javascript:alert(1)")).toBe("notWeb");
    expect(linksProblem(Array.from({ length: 11 }, (_, i) => `https://x${i}.example`).join("\n"))).toBe("tooMany");
    expect(linksProblem(`https://a.example/${"x".repeat(500)}`)).toBe("tooLong");
  });
});

describe("before publishing", () => {
  it("is ready when every required field and a problem are there", () => {
    expect(publishChecklist(READY)).toEqual([]);
  });

  it("lists what is missing, in the order of the form", () => {
    expect(publishChecklist(EMPTY_STATE).map((i) => i.field)).toEqual([
      "title",
      "niche_id",
      "maturity",
      "ask",
      "problem_statement",
      "summary",
      "problems",
    ]);
    expect(publishChecklist({ ...READY, problemMode: "new" }).map((i) => i.field)).toEqual([
      "new_problem.title",
      "new_problem.statement",
    ]);
  });

  it("counts summary words and stops at 150", () => {
    expect(wordCount("  one two\nthree  ")).toBe(3);
    expect(wordCount("")).toBe(0);
    const long = Array.from({ length: 151 }, () => "word").join(" ");
    expect(publishChecklist({ ...READY, summary: long })).toEqual([{ field: "summary", code: "too_many_words" }]);
  });
});

describe("API refusals", () => {
  const teaser422 = {
    detail: {
      code: "invalid_teaser",
      message: "Some teaser fields need changes.",
      errors: [
        { field: "summary", code: "contains_email", message: "Remove the email address" },
        { field: "new_problem.title", code: "contains_url", message: "Remove the web address" },
        { field: "somewhere_else", code: "x", message: "ignored" },
      ],
    },
  };

  it("puts the sanitiser's findings next to their fields", () => {
    expect(fieldIssues(teaser422)).toEqual([
      { field: "summary", code: "contains_email" },
      { field: "new_problem.title", code: "contains_url" },
    ]);
    expect(saveRefusal(422, teaser422)).toEqual({ problem: "fields", fields: fieldIssues(teaser422) });
    expect(saveRefusal(422, { detail: { code: "unknown_niche", message: "" } }).fields).toEqual([
      { field: "niche_id", code: "unknown" },
    ]);
    expect(saveRefusal(422, { detail: [{ loc: ["body", "teaser"], msg: "x", type: "y" }] }).problem).toBe("validation");
  });

  it.each([
    [403, { detail: { code: "d1_required", message: "" } }, "d1Required"],
    [402, { detail: { code: "plan_limit", message: "", limit: 3, upgrade: null } }, "planLimit"],
    [409, { detail: { code: "attestation_text_outdated", message: "" } }, "attestationsChanged"],
    [409, { detail: { code: "nothing_to_publish", message: "" } }, "nothingToPublish"],
    [409, { detail: { code: "proposal_hidden", message: "" } }, "hidden"],
    [422, { detail: { code: "attestations_required", message: "", missing: ["created_it"] } }, "attestationsRequired"],
    [401, { detail: { code: "unauthenticated", message: "" } }, "signedOut"],
    [503, { detail: { code: "not_configured", message: "" } }, "unavailable"],
    [500, "Internal Server Error", "failed"],
  ] as const)("publish answered %i is %s", (status, body, problem) => {
    expect(publishRefusal(status, body).problem).toBe(problem);
  });

  it("keeps the plan's cap for the notice", () => {
    expect(publishRefusal(402, { detail: { code: "plan_limit", message: "", limit: 3 } }).limit).toBe(3);
  });

  it("keeps the next plan up of a 402, and none at the top of the ladder (REQ-BIL-08)", () => {
    const upgrade = { plan: "dev_pro_monthly", url: "/billing/upgrade?plan=dev_pro_monthly" };
    expect(publishRefusal(402, { detail: { code: "plan_limit", message: "", limit: 3, upgrade } }).upgrade).toBe(
      "dev_pro_monthly",
    );
    expect(publishRefusal(402, { detail: { code: "plan_limit", message: "", upgrade: null } }).upgrade).toBeUndefined();
  });

  it("lists what publishing needs (422 cannot_publish) by field", () => {
    const body = {
      detail: {
        code: "cannot_publish",
        message: "",
        errors: [
          { field: "maturity", code: "required", message: "" },
          { field: "problems", code: "problem_required", message: "" },
        ],
      },
    };
    expect(publishRefusal(422, body)).toEqual({
      problem: "fields",
      fields: [
        { field: "maturity", code: "required" },
        { field: "problems", code: "problem_required" },
      ],
    });
  });

  it.each([
    [413, { detail: { code: "too_large", message: "" } }, "tooLarge"],
    [413, undefined, "tooLarge"],
    [422, { detail: { code: "attachment_infected", message: "" } }, "infected"],
    [422, { detail: { code: "unsupported_file", message: "" } }, "unsupported"],
    [422, { detail: { code: "empty_file", message: "" } }, "empty"],
    [409, { detail: { code: "too_many_attachments", message: "" } }, "tooMany"],
    [0, undefined, "network"],
  ] as const)("upload answered %i is %s", (status, body, problem) => {
    expect(uploadRefusal(status, body).problem).toBe(problem);
  });
});

describe("attachments", () => {
  it("sends the type the API accepts for the file's extension", () => {
    expect(attachmentType("Pitch deck.PDF")).toBe("application/pdf");
    expect(attachmentType("notes.md")).toBe("text/markdown");
    expect(attachmentType("photo.jpeg")).toBe("image/jpeg");
    expect(attachmentType("readme")).toBeNull();
    expect(attachmentType("setup.exe")).toBeNull();
  });

  it("formats sizes in decimal units", () => {
    expect(fileSizeParts(512)).toEqual({ key: "fileSizeBytes", value: 512 });
    expect(fileSizeParts(820_400)).toEqual({ key: "fileSizeKb", value: 820 });
    expect(fileSizeParts(4_210_000)).toEqual({ key: "fileSizeMb", value: 4.2 });
  });

  it("uploads the raw bytes with the name percent-encoded in a header, never in the URL", async () => {
    const send = vi.fn(async () =>
      Response.json(
        { id: "a1", file_name: "Mpango wa kazi – v2.pdf", content_type: "application/pdf", size_bytes: 4, sha256: "x", av_status: "clean" },
        { status: 201 },
      ),
    );
    const file = new Blob(["%PDF"]);
    const outcome = await uploadAttachment("p/1", file, "Mpango wa kazi – v2.pdf", "application/pdf", send);
    expect(outcome.ok).toBe(true);
    const [url, init] = send.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/me/proposals/p%2F1/attachments");
    expect(url).not.toContain("Mpango");
    const headers = new Headers(init.headers);
    expect(headers.get("X-File-Name")).toBe("Mpango%20wa%20kazi%20%E2%80%93%20v2.pdf");
    expect(headers.get("Content-Type")).toBe("application/pdf");
    expect(init.body).toBe(file);
  });

  it("reports an infected file and a lost connection", async () => {
    const infected = vi.fn(async () =>
      Response.json({ detail: { code: "attachment_infected", message: "" } }, { status: 422 }),
    );
    expect(await uploadAttachment("p1", new Blob(["x"]), "a.txt", "text/plain", infected)).toMatchObject({
      ok: false,
      problem: "infected",
    });
    const offline = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(await uploadAttachment("p1", new Blob(["x"]), "a.txt", "text/plain", offline)).toMatchObject({
      ok: false,
      problem: "network",
    });
  });
});

describe("calls", () => {
  function client(response: Response) {
    const calls: Array<[string, string, unknown]> = [];
    const answer = async (method: string, path: string, options: unknown) => {
      calls.push([method, path, options]);
      const text = await response.clone().text();
      return response.ok ? { data: JSON.parse(text), response } : { error: JSON.parse(text), response };
    };
    return {
      calls,
      api: {
        GET: (p: string, o: unknown) => answer("GET", p, o),
        POST: (p: string, o: unknown) => answer("POST", p, o),
        PATCH: (p: string, o: unknown) => answer("PATCH", p, o),
        PUT: (p: string, o: unknown) => answer("PUT", p, o),
        DELETE: (p: string, o: unknown) => answer("DELETE", p, o),
      } as never,
    };
  }

  it("creates the draft with POST the first time and PATCHes it afterwards", async () => {
    const fake = client(Response.json({ id: "p1" }, { status: 201 }));
    await saveDraft(null, { teaser: { title: "x" } }, fake.api);
    await saveDraft("p1", { teaser: { title: "y" } }, fake.api);
    expect(fake.calls.map(([method, path]) => `${method} ${path}`)).toEqual([
      "POST /api/me/proposals",
      "PATCH /api/me/proposals/{proposal_id}",
    ]);
  });

  it("sends the attestation text version with the three statements", async () => {
    const fake = client(Response.json({ cert_id: "C1" }));
    const text = { version: "2026-09-29.1", sha256: "ab", statements: [] };
    const statements = { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true };
    await publish("p1", text, statements, fake.api);
    expect(fake.calls[0][2]).toEqual({
      params: { path: { proposal_id: "p1" } },
      body: { attestations: statements, attestation_text_version: "2026-09-29.1" },
    });
  });

  it("searches problems with a trimmed query and no empty filters", async () => {
    const fake = client(Response.json({ items: [] }));
    await searchProblems({ q: "  maziwa  ", niche: "" }, fake.api);
    expect(fake.calls[0][2]).toEqual({ params: { query: { q: "maziwa", niche: undefined, limit: 20 } } });
  });
});
