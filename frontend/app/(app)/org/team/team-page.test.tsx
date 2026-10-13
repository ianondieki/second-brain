import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithPageStrings } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Membership } from "../membership";
import type { TeamCalls, TeamOutcome } from "./calls";
import type { OrgTeam } from "./team";

// REQ-TEN-02 (P28 track C; docs/spec/07 item 1 Team; AT-C-1, AT-C-2, AT-C-3 on the page): what an owner, an admin and
// a member see on Organisation › Team, each write's request, the API's refusals in the page's words, the fresh-code
// step before an invitation, and the public demo's switched-off lines. The page's checks of spec 07: one primary
// action at most, at most two chips per member.

const ORG_ID = "0199c000-0000-7000-8000-0000000000a1";
const ORG_NAME = "Telco A (fixture)";
const GRACE = "0199c000-0000-7000-8000-00000000c001";
const PETER = "0199c000-0000-7000-8000-00000000c002";
const RITA = "0199c000-0000-7000-8000-00000000c003";
const FAITH = "0199c000-0000-7000-8000-00000000c004";

const mocks = vi.hoisted(() => ({
  refresh: vi.fn(),
  push: vi.fn(),
  calls: null as unknown as TeamCalls,
  confirmStepUp: vi.fn(),
}));

const state = vi.hoisted(() => ({
  membership: null as Membership | null,
  team: null as { kind: "ok"; team: OrgTeam } | { kind: "refused"; refusal: string } | null,
  niches: [] as { slug: string; label: string }[],
  verification: "e2" as string | null,
  demo: false,
  enrolled: true,
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
  // As the real one: only the chosen keys of the namespace.
  pickedStrings: async (namespace: string, keys: string[]) => {
    const all = (en as unknown as Record<string, Record<string, unknown>>)[namespace];
    return { [namespace]: Object.fromEntries(keys.map((key) => [key, all[key]])) };
  },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: mocks.refresh }),
  redirect: () => {
    throw new Error("redirect");
  },
  unstable_rethrow: () => undefined,
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ nav, children }: { nav: ReactNode; children: ReactNode }) => (
    <>
      {nav}
      <main>{children}</main>
    </>
  ),
}));
vi.mock("@/lib/public-demo", () => ({ publicDemoOn: () => state.demo }));
vi.mock("../data", () => ({
  orgContext: async () => ({
    me: { user: { id: GRACE }, mfa: { enrolled: state.enrolled } },
    memberships: state.membership ? [state.membership] : [],
    org: state.membership,
    missing: state.membership ? null : "none",
    query: "",
  }),
}));
vi.mock("./team-data", () => ({
  getTeam: async () => state.team,
  getOrgNiches: async () => state.niches,
}));
vi.mock("../scout-data", () => ({
  getVerification: async () => state.verification,
  readOrgPlans: async () => [
    { code: "org_claimed", name: "Claimed (Free)" },
    { code: "org_growth", name: "Growth" },
  ],
}));
vi.mock("./calls", async (original) => ({
  ...(await original<typeof import("./calls")>()),
  teamCalls: () => mocks.calls,
}));
vi.mock("@/components/tracker/calls", async (original) => ({
  ...(await original<typeof import("@/components/tracker/calls")>()),
  confirmStepUp: mocks.confirmStepUp,
}));

const { default: TeamPage } = await import("./page");

const owner: Membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["owner", "admin"] };
const adminOnly: Membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["admin"] };
const reviewer: Membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] };

function team(overrides: Partial<OrgTeam> = {}): OrgTeam {
  return {
    members: [
      { user_id: GRACE, name: "Grace Mwangi", email: "owner@telco-a.example", roles: ["admin", "owner"], joined_at: "2026-09-01T07:00:00Z" },
      { user_id: PETER, name: "Peter Kamau", email: "signatory@telco-a.example", roles: ["signatory"], joined_at: "2026-09-02T07:00:00Z" },
      {
        user_id: RITA,
        name: "Rita Njeri",
        email: "reviewer@telco-a.example",
        roles: ["finance", "viewer", "reviewer"],
        joined_at: "2026-09-03T07:00:00Z",
      },
      { user_id: FAITH, name: "Faith Achieng", email: "finance@telco-a.example", roles: ["finance"], joined_at: "2026-09-04T07:00:00Z" },
    ],
    invitations: [
      {
        id: "inv-1",
        email: "wanjiru@telco-a.example",
        roles: ["reviewer"],
        created_at: "2026-10-10T07:00:00Z",
        expires_at: "2026-10-17T07:00:00Z",
        expired: false,
        invited_by_name: "Grace Mwangi",
      },
      {
        id: "inv-2",
        email: "otieno@telco-a.example",
        roles: ["viewer", "finance"],
        created_at: "2026-09-20T07:00:00Z",
        expires_at: "2026-09-27T07:00:00Z",
        expired: true,
        invited_by_name: "Grace Mwangi",
      },
    ],
    niche_defaults: [{ niche_slug: "telecom", niche_name: "Telecom", user_id: RITA, name: "Rita Njeri" }],
    escalation_contact: { user_id: PETER, name: "Peter Kamau" },
    ...overrides,
  };
}

const ok: TeamOutcome<unknown> = { ok: true, value: null };

function fakeCalls(): TeamCalls {
  return {
    invite: vi.fn(async () => ok),
    resend: vi.fn(async () => ok),
    revoke: vi.fn(async () => ok),
    remove: vi.fn(async () => ok),
    setRoles: vi.fn(async () => ok),
    setNicheDefaults: vi.fn(async () => ok),
    setEscalationContact: vi.fn(async () => ok),
  };
}

beforeEach(() => {
  state.membership = owner;
  state.team = { kind: "ok", team: team() };
  state.niches = [
    { slug: "telecom", label: "ICT › Networks & Telecommunications" },
    { slug: "fintech", label: "Financial services › Payments" },
  ];
  state.verification = "e2";
  state.demo = false;
  state.enrolled = true;
  mocks.calls = fakeCalls();
  mocks.refresh.mockReset();
  mocks.push.mockReset();
  mocks.confirmStepUp.mockReset();
});
afterEach(cleanup);

async function renderPage() {
  const node = await TeamPage({ searchParams: Promise.resolve({}) } as never);
  // Only the strings the page sends: a namespace it forgets shows as raw keys and fails here.
  return renderWithPageStrings(<>{await resolveServerTree(node)}</>);
}

const memberRow = (userId: string) => document.querySelector<HTMLElement>(`[data-member="${userId}"]`)!;

/** The removal's confirm button, once its step (a chunk loaded on the press) is drawn. */
const confirmButton = (row: HTMLElement) =>
  waitFor(() => {
    const button = row.querySelector<HTMLElement>("[data-remove-confirm]");
    expect(button).not.toBeNull();
    return button!;
  });

describe("an owner's Team page", () => {
  it("lists the members with email, joined date and at most two role chips, the rest in words", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Team");
    expect(document.querySelector("[data-verification]")?.textContent).toBe("Registration documents verified (E2)");
    expect(screen.getByText("4 people")).toBeTruthy();
    const grace = memberRow(GRACE);
    expect(within(grace).getByRole("heading", { level: 3 }).textContent).toBe("Grace MwangiYou");
    expect(within(grace).getByText("owner@telco-a.example")).toBeTruthy();
    expect(within(grace).getByText("Joined 1 Sep 2026")).toBeTruthy();
    expect([...grace.querySelectorAll("[data-chip]")].map((c) => c.textContent)).toEqual(["Owner", "Admin"]);
    const rita = memberRow(RITA);
    expect([...rita.querySelectorAll("[data-chip]")].map((c) => c.textContent)).toEqual(["Reviewer", "Finance"]);
    expect(within(rita).getByText("Also viewer")).toBeTruthy();
    for (const row of document.querySelectorAll("[data-member]")) {
      expect(row.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2); // docs/spec/07 item 2
    }
  });

  it("offers role changes on every member and removal on everyone but themself; Send is the one primary action", async () => {
    await renderPage();
    expect(within(memberRow(GRACE)).queryByRole("button", { name: "Remove Grace Mwangi" })).toBeNull();
    expect(within(memberRow(GRACE)).getByRole("button", { name: "Change roles of Grace Mwangi" })).toBeTruthy();
    expect(within(memberRow(PETER)).getByRole("button", { name: "Remove Peter Kamau" })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Send invitation" }).hasAttribute("data-primary")).toBe(true);
    // Every role, the owner's to give.
    const roles = within(screen.getByRole("group", { name: "Roles" })).getAllByRole("checkbox");
    expect(roles.map((r) => (r as HTMLInputElement).value)).toEqual([
      "owner",
      "admin",
      "signatory",
      "reviewer",
      "finance",
      "viewer",
    ]);
    expect(roles.every((r) => !(r as HTMLInputElement).checked)).toBe(true);
  });

  it("lists open invitations with who sent them and until when, or that the link expired", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { name: "2 open invitations" })).toBeTruthy();
    const open = document.querySelector<HTMLElement>('[data-invitation="wanjiru@telco-a.example"]')!;
    expect(within(open).getByText("reviewer")).toBeTruthy(); // drawn with a capital (first-letter), read as words
    expect(within(open).getByText("Invited by Grace Mwangi on 10 Oct 2026")).toBeTruthy();
    expect(within(open).getByText("Link works until 17 Oct 2026")).toBeTruthy();
    expect(open.querySelector("[data-chip]")).toBeNull();
    const old = document.querySelector<HTMLElement>('[data-invitation="otieno@telco-a.example"]')!;
    expect(within(old).getByText("finance and viewer")).toBeTruthy();
    expect(old.querySelector("[data-chip]")?.textContent).toBe("Expired");
    expect(within(old).getByText("Link expired on 27 Sep 2026. Resend it to send a new one.")).toBeTruthy();
    expect(within(old).getByRole("button", { name: "Resend the invitation to otieno@telco-a.example" })).toBeTruthy();
  });

  it("shows each niche with a select of the members who may review, and the escalation contact", async () => {
    await renderPage();
    const telecom = screen.getByLabelText("ICT › Networks & Telecommunications") as HTMLSelectElement;
    expect(telecom.value).toBe(RITA);
    expect([...telecom.options].map((o) => o.textContent)).toEqual(["Nobody", "Grace Mwangi", "Peter Kamau", "Rita Njeri"]);
    expect((screen.getByLabelText("Financial services › Payments") as HTMLSelectElement).value).toBe("");
    const contact = screen.getByLabelText("Escalation contact") as HTMLSelectElement;
    expect(contact.value).toBe(PETER);
    expect(contact.options[0].textContent).toBe("Nobody besides the admins");
  });

  it("stops at the cap of open invitations with one notice instead of the form", async () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      ...team().invitations![0],
      id: `inv-${i}`,
      email: `person${i}@telco-a.example`,
    }));
    state.team = { kind: "ok", team: team({ invitations: many }) };
    await renderPage();
    expect(document.querySelector("[data-invite-cap]")?.textContent).toBe(
      "20 invitations are open, the most at once. Revoke one, or wait until one is accepted, to invite someone else.",
    );
    expect(document.querySelector("[data-invite-form]")).toBeNull();
  });

  it("offers Help when the organisation lists no niche", async () => {
    state.niches = [];
    state.team = { kind: "ok", team: team({ niche_defaults: [] }) };
    await renderPage();
    const empty = document.querySelector<HTMLElement>('[data-team="defaults"] [data-empty-state]')!;
    expect(empty.textContent).toContain(en.orgTeam.noNiches);
    expect(within(empty).getByRole("link").getAttribute("href")).toBe("/help");
  });
});

describe("before the organisation is verified", () => {
  it.each(["unclaimed", "pending", "rejected"])("offers no invitation form at %s, and says why with Help", async (level) => {
    state.verification = level;
    await renderPage();
    const line = document.querySelector<HTMLElement>("[data-invite-unverified]")!;
    expect(line.textContent).toContain(en.teamAdmin.refusal.org_not_verified);
    expect(within(line).getByRole("link", { name: "How verification works" }).getAttribute("href")).toBe("/help");
    expect(document.querySelector("[data-invite-form]")).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("keeps the form at E1, and when the level could not be read (the API still answers)", async () => {
    for (const level of ["e1", null]) {
      cleanup();
      state.verification = level;
      await renderPage();
      expect(document.querySelector("[data-invite-form]")).not.toBeNull();
    }
  });
});

describe("an admin who is not an owner", () => {
  it("cannot change roles, remove an owner or a signatory, or invite one", async () => {
    state.membership = adminOnly;
    await renderPage();
    expect(screen.queryByRole("button", { name: /^Change roles/ })).toBeNull();
    expect(within(memberRow(PETER)).queryByRole("button", { name: /Remove/ })).toBeNull();
    expect(within(memberRow(FAITH)).getByRole("button", { name: "Remove Faith Achieng" })).toBeTruthy();
    const roles = within(screen.getByRole("group", { name: "Roles" })).getAllByRole("checkbox");
    expect(roles.map((r) => (r as HTMLInputElement).value)).toEqual(["admin", "reviewer", "finance", "viewer"]);
    expect(screen.getByText(en.teamAdmin.rolesOwnerOnly)).toBeTruthy();
  });

  it("resends and revokes only the invitations an admin could have sent", async () => {
    state.membership = adminOnly;
    const signatoryInvite = { ...team().invitations![0], id: "inv-3", email: "sig@telco-a.example", roles: ["signatory" as const] };
    state.team = { kind: "ok", team: team({ invitations: [...team().invitations!, signatoryInvite] }) };
    await renderPage();
    const sig = document.querySelector<HTMLElement>('[data-invitation="sig@telco-a.example"]')!;
    expect(within(sig).queryByRole("button")).toBeNull();
    const own = document.querySelector<HTMLElement>('[data-invitation="wanjiru@telco-a.example"]')!;
    expect(within(own).getByRole("button", { name: /^Resend/ })).toBeTruthy();
  });
});

describe("a member who is neither owner nor admin", () => {
  it("reads the team, the defaults and the escalation contact, without a control or a primary action", async () => {
    state.membership = reviewer;
    state.team = {
      kind: "ok",
      team: team({ invitations: null, members: team().members.map((m) => ({ ...m, email: null })) }),
    };
    await renderPage();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(document.querySelector('[data-team="invitations"]')).toBeNull();
    expect(screen.queryByText("owner@telco-a.example")).toBeNull();
    expect(screen.getByText(en.orgTeam.readOnly)).toBeTruthy();
    expect(document.querySelector('[data-niche-default="telecom"]')?.textContent).toBe("Rita Njeri");
    expect(document.querySelector('[data-niche-default="fintech"]')?.textContent).toBe("Nobody yet");
    expect(document.querySelector("[data-escalation-contact]")?.textContent).toBe(
      "Peter Kamau hears of escalations with your admins.",
    );
  });
});

describe("in the public demo", () => {
  it("switches off invitations, removals and role changes, and keeps the defaults and the contact", async () => {
    state.demo = true;
    await renderPage();
    const locked = [...document.querySelectorAll("[data-demo-locked]")].map((p) => p.textContent);
    expect(locked).toEqual([en.publicDemo.changeLocked, en.publicDemo.changeLocked]);
    expect(document.querySelector('[data-demo-locked="change"]')).not.toBeNull();
    expect(document.querySelector("[data-invite-form]")).toBeNull();
    expect(document.querySelector("[data-member-actions]")).toBeNull();
    expect(document.querySelector("[data-invitation-actions]")).toBeNull();
    expect(document.querySelector("[data-niche-defaults]")).not.toBeNull();
    expect(document.querySelector("[data-escalation-form]")).not.toBeNull();
    // The open invitations are still listed.
    expect(document.querySelector('[data-invitation="wanjiru@telco-a.example"]')).not.toBeNull();
  });
});

describe("the writes on the page", () => {
  function invite(email: string, roles: string[]) {
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: email } });
    for (const role of roles) fireEvent.click(screen.getByRole("checkbox", { name: new RegExp(`^${role}`, "i") }));
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
  }

  it("asks for an address and a role before sending anything", async () => {
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect(screen.getByText(en.teamAdmin.emailRequired)).toBeTruthy();
    expect(screen.getByText(en.teamAdmin.rolesRequired)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText("Email address"));
    expect(mocks.calls.invite).not.toHaveBeenCalled();
  });

  it("invites with the chosen roles, says so and reads the page again", async () => {
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    invite(" wanjiku@telco-a.example ", ["Finance", "Reviewer"]);
    await waitFor(() => expect(mocks.calls.invite).toHaveBeenCalledWith("wanjiku@telco-a.example", ["reviewer", "finance"]));
    await waitFor(() =>
      expect(document.querySelector("[data-invited]")?.textContent).toBe(
        "Invitation sent to wanjiku@telco-a.example. The link works for 7 days.",
      ),
    );
    expect(mocks.refresh).toHaveBeenCalled();
    expect((screen.getByLabelText("Email address") as HTMLInputElement).value).toBe("");
  });

  it("asks for a fresh code when the API wants one, then sends the invitation once more", async () => {
    vi.mocked(mocks.calls.invite)
      .mockResolvedValueOnce({ ok: false, refusal: "stepUp" })
      .mockResolvedValueOnce(ok);
    mocks.confirmStepUp.mockResolvedValue({ ok: true });
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    invite("wanjiku@telco-a.example", ["Viewer"]);
    const code = await screen.findByLabelText("Authenticator code");
    expect(document.querySelector("[data-invite-form]")).toBeNull();
    fireEvent.change(code, { target: { value: "123456" } });
    await waitFor(() => expect(document.querySelector('[data-step-up="code"][data-hydrated="true"]')).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" }));
    await waitFor(() => expect(mocks.calls.invite).toHaveBeenCalledTimes(2));
    expect(mocks.confirmStepUp).toHaveBeenCalledWith("123456");
    await waitFor(() => expect(document.querySelector("[data-invited]")).not.toBeNull());
  });

  it.each([
    [{ refusal: "already_member" }, en.teamAdmin.refusal.already_member],
    [{ refusal: "already_invited" }, en.teamAdmin.refusal.already_invited],
    [{ refusal: "too_many_invitations", limit: 20 }, "20 invitations are open, the most at once. Revoke one, or wait until one is accepted."],
    [{ refusal: "protected_role" }, en.teamAdmin.refusal.protected_role],
    [{ refusal: "invalid_email" }, en.teamAdmin.refusal.invalid_email],
    [{ refusal: "rate_limited" }, `${en.teamAdmin.refusal.rate_limited}${en.retryAfter.later}`],
    [{ refusal: "rate_limited", retryAfter: 240 }, `${en.teamAdmin.refusal.rate_limited}Try again in about 4 minutes.`],
    [{ refusal: "rate_limited", retryAfter: 7200 }, `${en.teamAdmin.refusal.rate_limited}Try again in about 2 hours.`],
    [{ refusal: "public_demo_locked" }, en.teamAdmin.refusal.public_demo_locked],
    [{ refusal: "network" }, en.teamAdmin.refusal.network],
  ])("says %o in the page's words", async (refusal, sentence) => {
    vi.mocked(mocks.calls.invite).mockResolvedValueOnce({ ok: false, ...refusal } as TeamOutcome<unknown>);
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    invite("someone@telco-a.example", ["Viewer"]);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(sentence);
    await waitFor(() => expect(document.activeElement).toBe(alert)); // focus moves in an effect after the paint
  });

  it("names the plan with more seats and links to its checkout when the seats are taken", async () => {
    vi.mocked(mocks.calls.invite).mockResolvedValueOnce({ ok: false, refusal: "plan_limit", limit: 3, upgrade: "org_growth" });
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    invite("someone@telco-a.example", ["Viewer"]);
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("p")?.textContent).toBe("Every seat on your plan is taken. Growth has more.");
    const link = within(alert).getByRole("link", { name: "Upgrade to Growth" });
    expect(link.getAttribute("href")).toBe(
      `/billing/upgrade?plan=org_growth&org=${ORG_ID}&next=%2Forg%2Fteam%3Forg%3D${ORG_ID}`,
    );
  });

  it("asks to sign in again when the session ended", async () => {
    vi.mocked(mocks.calls.setEscalationContact).mockResolvedValueOnce({ ok: false, refusal: "signedOut" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Save contact" }));
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("p")?.textContent).toBe(en.teamAdmin.refusal.signedOut);
    expect(within(alert).getByRole("link", { name: "Sign in again" }).getAttribute("href")).toBe(
      "/login?next=%2Forg%2Fteam",
    );
  });

  it("points to how verification works when the organisation is not verified yet", async () => {
    vi.mocked(mocks.calls.invite).mockResolvedValueOnce({ ok: false, refusal: "org_not_verified" });
    await renderPage();
    await waitFor(() => expect(document.querySelector('[data-invite-form][data-hydrated="true"]')).not.toBeNull());
    invite("someone@telco-a.example", ["Viewer"]);
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("p")?.textContent).toBe(en.teamAdmin.refusal.org_not_verified);
    expect(within(alert).getByRole("link", { name: "How verification works" }).getAttribute("href")).toBe("/help");
  });

  it("resends and revokes an open invitation", async () => {
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Resend the invitation to wanjiru@telco-a.example" }));
    await waitFor(() => expect(mocks.calls.resend).toHaveBeenCalledWith("inv-1"));
    expect(await screen.findByText("A new link went to wanjiru@telco-a.example. The earlier one no longer works.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revoke the invitation to otieno@telco-a.example" }));
    await waitFor(() => expect(mocks.calls.revoke).toHaveBeenCalledWith("inv-2"));
    expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });

  it("says a resend that raced an acceptance, and reads the list again", async () => {
    vi.mocked(mocks.calls.resend).mockResolvedValueOnce({ ok: false, refusal: "conflict" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Resend the invitation to wanjiru@telco-a.example" }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.teamAdmin.refusal.conflict);
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it("re-reads the list when an invitation was closed meanwhile", async () => {
    vi.mocked(mocks.calls.revoke).mockResolvedValueOnce({ ok: false, refusal: "invitation_closed" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Revoke the invitation to wanjiru@telco-a.example" }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.teamAdmin.refusal.invitation_closed);
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it("asks in place before removing a member, then removes them", async () => {
    await renderPage();
    const row = memberRow(PETER);
    fireEvent.click(within(row).getByRole("button", { name: "Remove Peter Kamau" }));
    const question = await within(row).findByText(
      `Remove Peter Kamau from ${ORG_NAME}? They lose access at once, and engagements assigned to them become unassigned.`,
    );
    await waitFor(() => expect(document.activeElement).toBe(question));
    expect(mocks.calls.remove).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(within(row).getByRole("button", { name: "Remove Peter Kamau" })),
    );
    fireEvent.click(within(row).getByRole("button", { name: "Remove Peter Kamau" }));
    fireEvent.click(await confirmButton(row));
    await waitFor(() => expect(mocks.calls.remove).toHaveBeenCalledWith(PETER));
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it.each([
    ["last_owner", en.teamAdmin.refusal.last_owner],
    ["protected_member", en.teamAdmin.refusal.protected_member],
  ])("says %s beside the member it concerns", async (refusal, sentence) => {
    vi.mocked(mocks.calls.remove).mockResolvedValueOnce({ ok: false, refusal } as TeamOutcome<unknown>);
    await renderPage();
    const row = memberRow(PETER);
    fireEvent.click(within(row).getByRole("button", { name: "Remove Peter Kamau" }));
    fireEvent.click(await confirmButton(row));
    expect((await within(row).findByRole("alert")).textContent).toBe(sentence);
  });

  it("changes a member's roles (an owner's step)", async () => {
    await renderPage();
    const row = memberRow(FAITH);
    fireEvent.click(within(row).getByRole("button", { name: "Change roles of Faith Achieng" }));
    const group = await within(row).findByRole("group", { name: "Roles of Faith Achieng" });
    expect((within(group).getByRole("checkbox", { name: "Finance" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(group).getByRole("checkbox", { name: "Reviewer" }));
    fireEvent.click(within(row).getByRole("button", { name: "Save roles" }));
    await waitFor(() => expect(mocks.calls.setRoles).toHaveBeenCalledWith(FAITH, ["reviewer", "finance"]));
    expect(await within(row).findByText("Roles saved.")).toBeTruthy();
  });

  it("refuses to save a member with no role", async () => {
    await renderPage();
    const row = memberRow(FAITH);
    fireEvent.click(within(row).getByRole("button", { name: "Change roles of Faith Achieng" }));
    fireEvent.click(await within(row).findByRole("checkbox", { name: "Finance" }));
    fireEvent.click(within(row).getByRole("button", { name: "Save roles" }));
    expect(within(row).getByText(en.teamAdmin.rolesRequired)).toBeTruthy();
    expect(mocks.calls.setRoles).not.toHaveBeenCalled();
  });

  it("saves the default reviewer of every niche as one set", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Financial services › Payments"), { target: { value: PETER } });
    fireEvent.change(screen.getByLabelText("ICT › Networks & Telecommunications"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));
    await waitFor(() =>
      expect(mocks.calls.setNicheDefaults).toHaveBeenCalledWith([{ niche_slug: "fintech", user_id: PETER }]),
    );
    expect(await screen.findByText(en.teamAdmin.defaultsSaved)).toBeTruthy();
  });

  it("says a default the API refuses in words", async () => {
    vi.mocked(mocks.calls.setNicheDefaults).mockResolvedValueOnce({ ok: false, refusal: "invalid_default_reviewer" });
    await renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.teamAdmin.refusal.invalid_default_reviewer);
  });

  it("clears the escalation contact", async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText("Escalation contact"), { target: { value: "" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save contact" }));
    });
    expect(mocks.calls.setEscalationContact).toHaveBeenCalledWith(null);
    expect(await screen.findByText(en.teamAdmin.escalationSaved)).toBeTruthy();
  });
});

describe("when the team cannot be shown", () => {
  it("asks for the second factor first", async () => {
    state.team = { kind: "refused", refusal: "mfa_required" };
    await renderPage();
    expect(screen.getByRole("link", { name: en.orgProposal.action.enterCode }).getAttribute("href")).toBe("/auth/mfa");
  });

  it("says a failed read in one sentence with Try again", async () => {
    state.team = { kind: "refused", refusal: "generic" };
    await renderPage();
    expect(screen.getByText(en.orgTeam.readFailed)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Try again" }).getAttribute("href")).toBe("/org/team");
  });

  it("sends someone without an organisation to its home", async () => {
    state.membership = null;
    await renderPage();
    expect(screen.getByRole("link", { name: en.inbox.emptyAction }).getAttribute("href")).toBe("/org");
  });
});
