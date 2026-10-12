import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EngagementScreen } from "./EngagementScreen";
import { IpNudge } from "./IpNudge";

// REQ-DEV-04 (P27 track E; docs/spec/06 6.1 "non-blocking nudge"): one dismissible note under the developer's
// send_nda step about KIPI and KECOBO, while the API's `ip_nudge` says so; Dismiss posts and hides it.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));
vi.mock("./data", () => ({
  engagementHistory: async () => ({ engagement_id: "e", chain_verified: true, events: [], endorsements: [] }),
  orgMembers: async () => [],
  tier2ShareState: async () => null,
  engagementDocument: async () => null,
}));
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ api: { POST: post } }));

afterEach(() => {
  cleanup();
  post.mockReset();
  refresh.mockReset();
});

const sendNda = (overrides = {}) =>
  detail({
    state: "CONTACT_MADE",
    stage_group: "contact_nda",
    actions: ["send_nda", "withdraw"],
    awaiting: [{ command: "send_nda", party: "developer" }],
    whose_turn: ["developer"],
    ip_nudge: true,
    ...overrides,
  });

async function nudge(d = sendNda()) {
  return renderWithIntl(<>{await resolveServerTree(<IpNudge detail={d} />)}</>);
}

describe("the IP note", () => {
  it("says the spec's nudge once, with KIPI's and KECOBO's sites (rel=noopener) and Dismiss", async () => {
    const { container } = await nudge();
    const note = container.querySelector("[data-ip-nudge] aside")!;
    expect(note.getAttribute("aria-label")).toBe("Before you share");
    expect(note.textContent).toContain(
      "Before you share a full proposal for the first time, you may want to look at KIPI's utility-model or patent filing and KECOBO's voluntary copyright registration. Neither is required here.",
    );
    const links = [...note.querySelectorAll("a")];
    expect(links.map((a) => [a.getAttribute("href"), a.getAttribute("rel")])).toEqual([
      ["https://kipi.go.ke", "noopener"],
      ["https://copyright.go.ke", "noopener"],
    ]);
    expect(links[0].textContent).toBe("KIPI (kipi.go.ke) (opens in a new tab)");
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeTruthy();
  });

  it("is absent once dismissed (ip_nudge false) and never on the organisation's tracker", async () => {
    expect((await nudge(sendNda({ ip_nudge: false }))).container.textContent).toBe("");
    cleanup();
    expect((await nudge(sendNda({ my_party: "org", ip_nudge: true }))).container.textContent).toBe("");
  });

  it("Dismiss posts to the API, hides the note and refreshes the tracker", async () => {
    post.mockResolvedValue({ response: new Response(null, { status: 204 }) });
    const { container } = await nudge();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Dismiss" })));
    expect(post).toHaveBeenCalledWith("/api/me/profile/ip-nudge/dismiss");
    expect(container.querySelector("[data-ip-nudge]")!.hasAttribute("hidden")).toBe(true);
    expect(refresh).toHaveBeenCalled();
  });

  it("says so when Dismiss fails, and keeps the note", async () => {
    post.mockRejectedValue(new TypeError("offline"));
    const { container } = await nudge();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Dismiss" })));
    expect(screen.getByRole("alert").textContent).toBe("Could not dismiss the note. Try again.");
    expect(container.querySelector("[data-ip-nudge]")!.hasAttribute("hidden")).toBe(false);
  });

  it("sits in the turn card, under the developer's buttons", async () => {
    const me = { user: { id: "dev" }, mfa: { enrolled: true } } as unknown as Me;
    const tree = await resolveServerTree(
      await EngagementScreen({ detail: sendNda(), me, tab: "tracker", doc: null, basePath: "/dev/engagements" }),
    );
    const { container } = renderWithIntl(<>{tree}</>);
    const card = container.querySelector("[data-turn-card]")!;
    expect(card.querySelector("[data-ip-nudge]")).not.toBeNull();
    expect(card.lastElementChild!.hasAttribute("data-ip-nudge")).toBe(true);
    expect(card.querySelector("[data-command='send_nda']")).not.toBeNull();
  });
});
