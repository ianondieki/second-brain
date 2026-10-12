import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EngagementScreen } from "@/components/tracker/EngagementScreen";

// D-68 and REQ-PROV-06 (P27 review): the developer's tracker never loads the organisation's sheets. Both sheet modules
// are replaced by spies here: handed an organisation's `team` and an organisation-shaped `prior_knowledge` (the
// declaration window) by mistake, the developer's screen draws no team line, no declaration line or button, no
// received-declaration panel, and neither module is ever imported nor its component called.

const loaded = vi.hoisted(() => ({
  team: vi.fn(),
  declaration: vi.fn(),
  teamSheet: vi.fn(),
  declarationSheet: vi.fn(),
}));
vi.mock("@/components/team/TeamSheet", () => {
  loaded.team();
  return { TeamSheet: loaded.teamSheet };
});
vi.mock("@/components/provenance/DeclarationSheet", () => {
  loaded.declaration();
  return { DeclarationSheet: loaded.declarationSheet };
});
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/components/tracker/data", () => ({
  engagementHistory: async () => ({ engagement_id: "e", chain_verified: true, events: [], endorsements: [] }),
  orgMembers: async () => [],
  tier2ShareState: async () => null,
  engagementDocument: async () => null,
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));

const ME = { user: { id: "dev" }, mfa: { enrolled: true } } as unknown as Me;

describe("the developer's tracker, handed the organisation's facts by mistake", () => {
  it("draws none of them and never loads the organisation's sheets", async () => {
    const leaked = detail({
      my_party: "developer",
      ip_nudge: false,
      team: {
        assignee: { user_id: "u1", display_name: "Peter Kamau" },
        recommendations: { pursue: 1, pass: 2, discuss: 0 },
        mine: { stance: "pass", note: "Too early for us." },
      },
      prior_knowledge: {
        first_tier2_view_at: "2026-10-02T07:00:00Z",
        window_closes_on: "2026-10-16",
        declared_at: null,
        can_declare: true,
      } as never,
    });
    const tree = await resolveServerTree(
      await EngagementScreen({ detail: leaked, me: ME, tab: "tracker", doc: null, basePath: "/dev/engagements" }),
    );
    const { container } = renderWithIntl(<>{tree}</>);
    expect(container.querySelector("[data-turn-card]")).not.toBeNull();
    expect(container.querySelector("[data-team-panel]")).toBeNull();
    expect(container.querySelector("[data-declaration]")).toBeNull();
    expect(container.querySelector("[data-received-declaration]")).toBeNull();
    expect(container.querySelector("[data-opens='team'], [data-opens='declaration']")).toBeNull();
    expect(container.textContent).not.toMatch(/Peter Kamau|Too early|Recommended|Declare prior knowledge|declaration/i);
    // Let any dynamic import that was wrongly started settle before asserting it never ran.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(loaded.team).not.toHaveBeenCalled();
    expect(loaded.declaration).not.toHaveBeenCalled();
    expect(loaded.teamSheet).not.toHaveBeenCalled();
    expect(loaded.declarationSheet).not.toHaveBeenCalled();
  });
});
