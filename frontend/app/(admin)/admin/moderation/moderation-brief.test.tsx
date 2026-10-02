import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { CaseRow } from "./CaseRow";
import { caseKindLabel, caseReasons, fieldKey, reasonTone, type Case } from "./moderation";

// REQ-DIR-05 with REQ-MOD-01: every organisation's Problem Brief waits in the moderation queue. Its reason and its
// "Who is affected" field read in words (not "Another reason" or "Other field"), and the queue names it a Problem
// Brief by its organisation, so staff can tell it from a developer's problem.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));

afterEach(cleanup);

function briefCase(extra: Partial<Case> = {}): Case {
  return {
    id: "01a0f016-2e64-7294-9e44-77fa421dce10",
    subject_type: "problem",
    subject_id: "01a0f070-0000-7000-8000-000000000001",
    reasons: ["new_org_brief"],
    source: "prescreen",
    status: "open",
    created_at: "2026-10-01T07:00:00Z",
    subject_state: "clear",
    subject_version_id: null,
    preview: { title: "Tower sites go dark when fuel runs out", text: "Field teams learn about empty tanks too late." },
    fields: [
      { name: "title", text: "Tower sites go dark when fuel runs out" },
      { name: "statement", text: "Field teams learn about empty tanks too late." },
      { name: "affected_group", text: "Rural subscribers" },
    ],
    flagged_fields: [],
    actions: ["approve", "reject"],
    blocked: null,
    decided_at: null,
    decided_by: null,
    brief_org: { id: "01a0ee62-0000-7000-8000-00000000000a", slug: "telco-a-fixture", name: "Telco A (fixture)" },
    ...extra,
  };
}

describe("a Brief's moderation case", () => {
  it("words its reason as routine information and its affected group as a field", () => {
    expect(caseReasons(["new_org_brief", "spam", "brand_new_reason"])).toEqual(["new_org_brief", "spam", "other"]);
    expect(reasonTone("new_org_brief")).toBe("info");
    expect(en.adminModeration.reason.new_org_brief).toBe("New Brief from an organisation");
    expect(fieldKey("affected_group")).toBe("affected_group");
    expect(en.adminModeration.field.affected_group).toBe("Who is affected");
  });

  it("is a Brief by its organisation, while a developer's problem stays a Problem", () => {
    expect(caseKindLabel(briefCase())).toEqual({ key: "briefBy", org: "Telco A (fixture)" });
    // Not in the directory: still a Problem Brief, by the reason it was filed with.
    expect(caseKindLabel(briefCase({ brief_org: null }))).toEqual({ key: "brief" });
    expect(caseKindLabel(briefCase({ brief_org: null, reasons: ["new_developer_problem"] }))).toEqual({ key: "problem" });
    expect(caseKindLabel(briefCase({ subject_type: "proposal", brief_org: null }))).toEqual({ key: "proposal" });
  });

  it("shows in the queue as Brief by <organisation> with its reason, within two marks", async () => {
    renderWithIntl(
      <table>
        <tbody>{await resolveServerTree(await CaseRow({ item: briefCase() }))}</tbody>
      </table>,
    );
    const row = screen.getByRole("row");
    expect(within(row).getByText("Brief by Telco A (fixture)")).toBeTruthy();
    const reason = row.querySelector("[data-chip='reason']")!;
    expect(reason.textContent).toBe("New Brief from an organisation");
    expect(reason.className).toContain("text-accent"); // information, not a warning
    expect(row.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
  });
});
