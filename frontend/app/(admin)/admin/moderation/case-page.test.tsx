import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import CasePage from "./cases/[id]/page";
import type { CaseView } from "./data";
import type { Case } from "./moderation";
import ModerationPage from "./page";

// REQ-MOD-01 (M2 walkthrough step 6): the case page shows the subject's Tier-1 text field by field, flags by a mark
// and a word (never colour alone), the reasons as fixed sentences, and the decision; the queue lists open cases with
// at most two tags and one primary action.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  notFound: () => {
    throw new Error("notFound");
  },
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("../AdminShell", () => ({ AdminShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));

const staff = vi.hoisted(() => ({ role: "moderator" as "admin" | "moderator" | "support" }));
vi.mock("../staff", () => ({ staffContext: async () => ({ me: {}, role: staff.role }) }));

const data = vi.hoisted(() => ({
  view: { kind: "ok", data: { item: null, nextId: null } } as { kind: "ok"; data: CaseView } | { kind: "stepUp" },
  queue: [] as Case[],
}));
vi.mock("./data", () => ({
  getCase: async () => data.view,
  getQueue: async () => ({ kind: "ok", data: data.queue }),
}));

const ID = "01a0f016-2e64-7294-9e44-77fa421dce09";

function held(extra: Partial<Case> = {}): Case {
  return {
    id: ID,
    subject_type: "proposal",
    subject_id: "01a0f010-0000-7000-8000-000000000010",
    reasons: ["names_real_org_negative"],
    source: "regex",
    status: "held",
    created_at: "2026-09-30T05:00:00Z",
    subject_state: "held",
    subject_version_id: "01a0f011-0000-7000-8000-000000000011",
    preview: { title: "Clear loan-fee statements for SACCO members", text: "A member statement that lists each fee." },
    fields: [
      { name: "title", text: "Clear loan-fee statements for SACCO members" },
      { name: "problem_statement", text: "Members say SACCO B (fixture) overcharges them on late-repayment fees." },
      { name: "summary", text: "A member statement that lists each fee." },
    ],
    flagged_fields: ["problem_statement"],
    actions: ["approve", "reject"],
    blocked: null,
    decided_at: null,
    decided_by: null,
    ...extra,
  };
}

async function page(id = ID) {
  return renderWithIntl(<>{await resolveServerTree(await CasePage({ params: Promise.resolve({ id }) } as never))}</>);
}

beforeEach(() => {
  staff.role = "moderator";
  data.view = { kind: "ok", data: { item: held(), nextId: null } };
  data.queue = [];
});
afterEach(cleanup);

describe("the case page", () => {
  it("shows the Tier-1 text field by field and marks the flagged field with a mark and a word", async () => {
    const { container } = await page();
    expect(screen.getByRole("heading", { level: 1, name: "Clear loan-fee statements for SACCO members" })).toBeTruthy();
    const fields = [...container.querySelectorAll<HTMLElement>("[data-field]")];
    expect(fields.map((f) => f.dataset.field)).toEqual(["title", "problem_statement", "summary"]);
    const flagged = container.querySelector<HTMLElement>('[data-field="problem_statement"]')!;
    expect(flagged.hasAttribute("data-flagged")).toBe(true);
    const term = within(flagged).getByText("Flagged");
    expect(term.querySelector("svg")).not.toBeNull(); // the mark, beside the word
    expect(flagged.querySelector("dt")!.textContent).toBe("Problem statementFlagged");
    for (const name of ["title", "summary"]) {
      const field = container.querySelector<HTMLElement>(`[data-field="${name}"]`)!;
      expect(field.hasAttribute("data-flagged")).toBe(false);
      expect(within(field).queryByText("Flagged")).toBeNull();
    }
    expect(screen.getByText("Speaks negatively of a named organisation")).toBeTruthy();
    expect(screen.getByText("Hidden until decided")).toBeTruthy();
    expect(screen.getByText("Approve to make it public, or reject to keep it hidden.")).toBeTruthy();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("data-primary")).toBe(true);
  });

  it("gives an unknown reason a fixed sentence, never the code", async () => {
    data.view = { kind: "ok", data: { item: held({ reasons: ["brand_new_reason"] }), nextId: null } };
    await page();
    expect(screen.getByText("Another reason from the check")).toBeTruthy();
    expect(screen.queryByText(/brand_new_reason/)).toBeNull();
  });

  it("shows a blocked case with a fixed sentence and no actions", async () => {
    data.view = {
      kind: "ok",
      data: { item: held({ actions: [], blocked: "own_content" }), nextId: null },
    };
    const { container } = await page();
    expect(screen.getByText("You wrote this, so another moderator has to decide it.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(screen.queryByText("Approve to make it public, or reject to keep it hidden.")).toBeNull();
  });

  it("shows a decided case with who decided it and when", async () => {
    data.view = {
      kind: "ok",
      data: {
        item: held({
          status: "approved",
          subject_state: "clear",
          actions: [],
          blocked: "already_decided",
          decided_at: "2026-09-30T07:30:00Z",
          decided_by: { id: "01a0f012-0000-7000-8000-000000000012", display_name: "Staff Moderator (demo)" },
        }),
        nextId: null,
      },
    };
    const { container } = await page();
    expect(container.querySelector('[data-decided="approved"]')!.textContent).toContain(
      "Approved by Staff Moderator (demo) on",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("reads an unknown or malformed id as a case that is not in the queue", async () => {
    data.view = { kind: "ok", data: { item: null, nextId: null } };
    await page();
    expect(screen.getByText("This case is not in the queue.")).toBeTruthy();
    cleanup();
    await page("not-a-uuid");
    expect(screen.getByText("This case is not in the queue.")).toBeTruthy();
  });

  it("asks for a fresh code in place of the case when the second factor is stale", async () => {
    data.view = { kind: "stepUp" };
    await page();
    expect(screen.getByLabelText("Code from your app")).toBeTruthy();
    expect(screen.getByText(/more than 12 hours ago/)).toBeTruthy();
  });

  it("tells support the section is not theirs", async () => {
    staff.role = "support";
    await page();
    expect(screen.getByText("Moderation is for staff admins and moderators.")).toBeTruthy();
  });
});

describe("the queue", () => {
  async function queue(view?: string) {
    const searchParams = Promise.resolve(view ? { view } : {});
    return renderWithIntl(<>{await resolveServerTree(await ModerationPage({ searchParams } as never))}</>);
  }

  it("lists open cases with at most two tags each, and the oldest one this moderator can decide as the primary action", async () => {
    const own = held({ id: "01a0f001-0000-7000-8000-000000000001", actions: [], blocked: "own_content" });
    const problem = held({
      id: "01a0f002-0000-7000-8000-000000000002",
      subject_type: "problem",
      subject_state: "clear",
      subject_version_id: null,
      reasons: ["new_developer_problem"],
      fields: [{ name: "title", text: "SACCO members cannot check loan fees" }],
      flagged_fields: [],
      preview: { title: "SACCO members cannot check loan fees", text: "Members see fees with no explanation." },
    });
    data.queue = [own, problem, held()];
    const { container } = await queue();
    const rows = [...container.querySelectorAll<HTMLElement>("[data-case]")];
    expect(rows).toHaveLength(3);
    for (const row of rows) expect(row.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    const primary = container.querySelectorAll<HTMLAnchorElement>("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Review the oldest case");
    expect(primary[0].getAttribute("href")).toBe(`/admin/moderation/cases/${problem.id}`);
    expect(within(rows[1]).getByText("Public while checked")).toBeTruthy();
    expect(within(rows[1]).getByText("New problem from a developer")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Open cases, oldest first" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("aria-current")).toBe("page");
  });

  it("shows an empty queue as one sentence and one action", async () => {
    const { container } = await queue();
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe("No cases are waiting for a decision.");
    expect(
      within(empty as HTMLElement)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["See decided cases"]);
  });

  it("lists decided cases with their outcome and who decided them", async () => {
    data.queue = [
      held({
        status: "rejected",
        subject_state: "rejected",
        actions: [],
        blocked: "already_decided",
        decided_at: "2026-09-30T07:30:00Z",
        decided_by: { id: "01a0f012-0000-7000-8000-000000000012", display_name: "Staff Admin (demo)" },
      }),
    ];
    const { container } = await queue("decided");
    expect(screen.getByRole("link", { name: "Decided" }).getAttribute("aria-current")).toBe("page");
    const row = container.querySelector<HTMLElement>("[data-case]")!;
    expect(within(row).getByText("Rejected")).toBeTruthy();
    expect(row.textContent).toContain("Rejected by Staff Admin (demo) on");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
  });
});
