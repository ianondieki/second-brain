import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { Me } from "@/lib/auth/routing";
import { detail, ORG_ID, SIGNATORY_ID } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EngagementScreen } from "@/components/tracker/EngagementScreen";
import type { TeamFacts } from "@/components/tracker/model";

import { AssigneeFilter, assignedToMe, isAssignedTo } from "./AssigneeFilter";
import { teamRefusal, type Team, type TeamCalls } from "./calls";
import { canTriage, TeamPanel } from "./TeamPanel";
import { TeamSheet } from "./TeamSheet";

// REQ-ENG-15 (P27 track C; D-68; docs/spec/03 roles): the organisation's team line and tally on its tracker, the Team
// sheet (assign, recommend, each refusal by its code), "Assigned to me", and the guard that a developer's tracker
// never draws any of it, even when handed a `team` by mistake.

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

beforeAll(() => {
  // jsdom has no <dialog> modal API.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(cleanup);

const ME_ID = "0199b000-0000-7000-8000-00000000c010";
const REVIEWER = { user_id: ME_ID, display_name: "Rita Njeri", role: "reviewer" as const };
const SIGNATORY = { user_id: SIGNATORY_ID, display_name: "Peter Kamau", role: "signatory" as const };
const OWNER = { user_id: "0199b000-0000-7000-8000-00000000c011", display_name: "Grace Mwangi", role: "owner" as const };

const FACTS: TeamFacts = {
  assignee: { user_id: SIGNATORY_ID, display_name: "Peter Kamau" },
  recommendations: { pursue: 2, pass: 0, discuss: 1 },
  mine: null,
};

function team(overrides: Partial<Team> = {}): Team {
  return {
    engagement_id: "e",
    members: [OWNER, SIGNATORY, REVIEWER],
    assignee: { user_id: SIGNATORY_ID, display_name: "Peter Kamau" },
    recommendations: [
      {
        user_id: OWNER.user_id,
        display_name: OWNER.display_name,
        stance: "pursue",
        note: "Fits our 2027 dairy programme.",
        updated_at: "2026-10-02T07:00:00Z",
      },
    ],
    ...overrides,
  };
}

const orgDetail = (overrides = {}) =>
  detail({ my_party: "org", my_roles: ["reviewer"], team: FACTS, prior_knowledge: null, actions: [], ...overrides });

async function panel(d = orgDetail()) {
  return renderWithIntl(<>{await resolveServerTree(<TeamPanel detail={d} myUserId={ME_ID} />)}</>);
}

describe("the team line on the organisation's tracker", () => {
  it("says who it is assigned to, the tally of recommendations, and opens the sheet from Change and See recommendations", async () => {
    const { container } = await panel();
    const line = container.querySelector("[data-team-panel]")!;
    expect(line.getAttribute("aria-label")).toBe("Your team on this engagement");
    expect(line.textContent).toContain("Assigned to Peter Kamau");
    expect(line.querySelector("[data-tally]")!.textContent).toContain("Recommended: pursue 2 · pass 0 · discuss 1");
    const openers = [...line.querySelectorAll("[data-opens='team']")].map((b) => b.textContent);
    expect(openers).toEqual(["Change", "See recommendations"]);
    // Server HTML: no primary action of its own.
    expect(container.querySelector("[data-primary]")).toBeNull();
  });

  it("says Assign when nobody is assigned, and 'Assigned to you' to the assignee", async () => {
    const none = await panel(
      orgDetail({ team: { ...FACTS, assignee: null, recommendations: { pursue: 0, pass: 0, discuss: 0 } } }),
    );
    expect(none.container.textContent).toContain("Not assigned yet");
    expect([...none.container.querySelectorAll("[data-opens='team']")].map((b) => b.textContent)).toEqual([
      "Assign",
      "Recommend",
    ]);
    // 44 px both ways: "Assign" alone is narrower than the target (docs/spec/07 item 6).
    for (const opener of none.container.querySelectorAll("[data-opens='team']")) {
      expect(opener.className.split(" ")).toEqual(expect.arrayContaining(["min-h-11", "min-w-11"]));
    }
    expect(none.container.textContent).toContain("No recommendations yet");
    cleanup();
    const mine = await panel(
      orgDetail({ team: { ...FACTS, assignee: { user_id: ME_ID, display_name: "Rita Njeri" } } }),
    );
    expect(mine.container.textContent).toContain("Assigned to you");
  });

  it("offers a finance or viewer member no Change and no Recommend (the API refuses them 403)", async () => {
    expect(canTriage({ my_roles: ["finance"] })).toBe(false);
    expect(canTriage({ my_roles: ["reviewer"] })).toBe(true);
    const { container } = await panel(orgDetail({ my_roles: ["finance"] }));
    expect([...container.querySelectorAll("[data-opens='team']")].map((b) => b.textContent)).toEqual([
      "See recommendations",
    ]);
    cleanup();
    const quiet = await panel(
      orgDetail({ my_roles: [], team: { ...FACTS, recommendations: { pursue: 0, pass: 0, discuss: 0 } } }),
    );
    expect(quiet.container.querySelectorAll("[data-opens='team']")).toHaveLength(0);
  });
});

describe("the developer's tracker (D-68)", () => {
  const ME = { user: { id: "dev" }, mfa: { enrolled: true } } as unknown as Me;

  it("never draws the team line, even when handed a team object by mistake", async () => {
    const leaked = detail({ my_party: "developer", team: FACTS, ip_nudge: false });
    const direct = await panel(leaked);
    expect(direct.container.querySelector("[data-team-panel]")).toBeNull();
    expect(direct.container.textContent).toBe("");
    cleanup();
    const tree = await resolveServerTree(
      await EngagementScreen({ detail: leaked, me: ME, tab: "tracker", doc: null, basePath: "/dev/engagements" }),
    );
    const { container } = renderWithIntl(<>{tree}</>);
    expect(container.querySelector("[data-team-panel]")).toBeNull();
    expect(container.querySelector("[data-opens='team']")).toBeNull();
    expect(container.textContent).not.toContain("Peter Kamau");
    expect(container.textContent).not.toMatch(/Recommended|Assigned to/);
  });

  it("draws the line on the organisation's tracker", async () => {
    const tree = await resolveServerTree(
      await EngagementScreen({
        detail: orgDetail(),
        me: { user: { id: ME_ID }, mfa: { enrolled: true } } as unknown as Me,
        tab: "tracker",
        doc: null,
        basePath: "/org/engagements",
      }),
    );
    const { container } = renderWithIntl(<>{tree}</>);
    // Inside the turn card, under the whose-turn banner.
    const card = container.querySelector("[data-turn-card]")!;
    expect(card.querySelector("[data-team-panel]")).not.toBeNull();
    expect(card.querySelector("[data-whose-turn] ~ [data-team-panel]")).not.toBeNull();
  });
});

function calls(overrides: Partial<TeamCalls> = {}): TeamCalls {
  return {
    read: vi.fn(async () => ({ ok: true as const, team: team() })),
    assign: vi.fn(async (id: string | null) => ({
      ok: true as const,
      team: team({
        assignee: id ? { user_id: id, display_name: id === OWNER.user_id ? OWNER.display_name : "?" } : null,
      }),
    })),
    recommend: vi.fn(async () => ({ ok: true as const, team: team() })),
    withdraw: vi.fn(async () => ({ ok: true as const, team: team() })),
    ...overrides,
  };
}

async function sheet(c: TeamCalls, { canTriage: triage = true, onClose = vi.fn() } = {}) {
  const view = renderWithIntl(
    <TeamSheet
      orgId={ORG_ID}
      engagementId="e"
      canTriage={triage}
      myUserId={ME_ID}
      focus="assign"
      onClose={onClose}
      calls={c}
    />,
  );
  await screen.findByText("Fits our 2027 dairy programme.");
  return view;
}

describe("the Team sheet", () => {
  it("lists the members it may be assigned to with their roles, nobody first, the assignee chosen", async () => {
    await sheet(calls());
    const dialog = screen.getByRole("dialog", { name: "Team on this engagement" });
    expect(dialog.textContent).toContain("Only your organisation sees this. The developer never does.");
    const group = within(dialog).getByRole("group", { name: "Assigned to" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.closest("label")!.textContent)).toEqual([
      "Nobody",
      "GMGrace MwangiOwner",
      "PKPeter KamauSignatory",
      "RNRita Njeri (you)Reviewer",
    ]);
    expect((within(group).getByRole("radio", { name: /Peter Kamau/ }) as HTMLInputElement).checked).toBe(true);
    // Focus lands on the assignment the opener asked for.
    await waitFor(() => expect(document.activeElement).toBe(within(group).getByRole("radio", { name: /Peter Kamau/ })));
  });

  it("assigns the chosen member and says so", async () => {
    const c = calls();
    await sheet(c);
    fireEvent.click(screen.getByRole("radio", { name: /Grace Mwangi/ }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Assign" })));
    expect(c.assign).toHaveBeenCalledWith(OWNER.user_id);
    expect(await screen.findByText("Assigned to Grace Mwangi.")).toBeTruthy();
  });

  it("unassigns with Nobody", async () => {
    const c = calls();
    await sheet(c);
    fireEvent.click(screen.getByRole("radio", { name: "Nobody" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Assign" })));
    expect(c.assign).toHaveBeenCalledWith(null);
    expect(await screen.findByText("Nobody is assigned now.")).toBeTruthy();
  });

  it.each([
    ["role_not_allowed", 403, "Only an owner, admin, reviewer or signatory can assign or recommend."],
    ["invalid_assignee", 422, "That person cannot be assigned."],
    ["unchanged", 409, "It is already assigned that way."],
    ["too_many_assignments", 429, "Try again in a few minutes."],
  ] as const)("says the API's %s refusal (%i) in place", async (code, status, words) => {
    const refusal = teamRefusal(status, { detail: { code, message: "server words" } });
    await sheet(calls({ assign: vi.fn(async () => ({ ok: false as const, refusal })) }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Assign" })));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(words);
    expect(alert.textContent).not.toContain("server words");
  });

  it("re-reads the team when someone changed it at the same moment (409 conflict)", async () => {
    const c = calls({ assign: vi.fn(async () => ({ ok: false as const, refusal: "conflict" as const })) });
    await sheet(c);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Assign" })));
    expect((await screen.findByRole("alert")).textContent).toContain("Someone changed this at the same moment");
    expect(c.read).toHaveBeenCalledTimes(2);
  });

  it("shows each member's recommendation with its note, as text", async () => {
    await sheet(
      calls({
        read: vi.fn(async () => ({
          ok: true as const,
          team: team({
            recommendations: [
              ...team().recommendations,
              {
                user_id: SIGNATORY_ID,
                display_name: "Peter Kamau",
                stance: "discuss",
                note: "<b>not markup</b>",
                updated_at: "2026-10-03T07:00:00Z",
              },
            ],
          }),
        })),
      }),
    );
    const list = screen.getByRole("dialog").querySelector("[data-team-recommendations] ul")!;
    const rows = within(list as HTMLElement).getAllByRole("listitem");
    expect(rows[0].textContent).toContain("Grace Mwangi");
    expect(rows[0].textContent).toContain("Pursue");
    expect(rows[1].textContent).toContain("Discuss");
    expect(rows[1].textContent).toContain("<b>not markup</b>");
    expect(rows[1].querySelector("b")).toBeNull();
  });

  it("records the caller's recommendation: a three-way choice and a one-line note of up to 200 characters", async () => {
    const c = calls();
    await sheet(c);
    const view = screen.getByRole("group", { name: "Your view" });
    expect(
      within(view)
        .getAllByRole("radio")
        .map((r) => r.closest("label")!.textContent),
    ).toEqual(["Pursue", "Pass", "Discuss"]);
    const note = screen.getByLabelText("Note (optional)") as HTMLInputElement;
    expect(note.maxLength).toBe(200);
    // No stance yet: said on the choice, nothing sent.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save recommendation" })));
    expect(c.recommend).not.toHaveBeenCalled();
    expect(screen.getByText("Choose pursue, pass or discuss.")).toBeTruthy();
    fireEvent.click(within(view).getByRole("radio", { name: "Discuss" }));
    fireEvent.change(note, { target: { value: "Ask about the chillers' power draw." } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save recommendation" })));
    expect(c.recommend).toHaveBeenCalledWith("discuss", "Ask about the chillers' power draw.");
    expect(await screen.findByText("Your recommendation is saved.")).toBeTruthy();
  });

  it("says invalid_note on the note field and puts focus there", async () => {
    await sheet(
      calls({
        recommend: vi.fn(async () => ({
          ok: false as const,
          refusal: teamRefusal(422, { detail: { code: "invalid_note", message: "x" } }),
        })),
      }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Pass" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save recommendation" })));
    const note = screen.getByLabelText("Note (optional)");
    expect(note.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(note.getAttribute("aria-describedby")!.split(" ").at(-1)!)!.textContent).toContain(
      "no invisible characters",
    );
    expect(document.activeElement).toBe(note);
  });

  it("refuses a note with an invisible or control character before sending (the API's one-line rule)", async () => {
    const c = calls();
    await sheet(c);
    fireEvent.click(screen.getByRole("radio", { name: "Pursue" }));
    const note = screen.getByLabelText("Note (optional)");
    fireEvent.change(note, { target: { value: `Looks right${String.fromCharCode(0x200b)} to me` } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save recommendation" })));
    expect(c.recommend).not.toHaveBeenCalled();
    expect(note.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(note);
  });

  it("offers Remove for the caller's own recommendation", async () => {
    const mine = team({
      recommendations: [
        { user_id: ME_ID, display_name: "Rita Njeri", stance: "pass", note: null, updated_at: "2026-10-02T07:00:00Z" },
      ],
    });
    const c = calls({ read: vi.fn(async () => ({ ok: true as const, team: mine })) });
    renderWithIntl(
      <TeamSheet orgId={ORG_ID} engagementId="e" canTriage myUserId={ME_ID} onClose={vi.fn()} calls={c} />,
    );
    await screen.findByText("Rita Njeri (you)", { selector: "span.font-semibold" });
    expect((screen.getByRole("radio", { name: "Pass" }) as HTMLInputElement).checked).toBe(true);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove" })));
    expect(c.withdraw).toHaveBeenCalled();
    expect(await screen.findByText("Your recommendation is removed.")).toBeTruthy();
  });

  it("is read-only for a member who cannot assign or recommend", async () => {
    await sheet(calls(), { canTriage: false });
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: "Assign" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save recommendation" })).toBeNull();
    expect(screen.getByText("Assigned to Peter Kamau.")).toBeTruthy();
  });

  it("says when the team cannot be read, with Try again", async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, refusal: "network" })
      .mockResolvedValue({ ok: true, team: team() });
    renderWithIntl(
      <TeamSheet
        orgId={ORG_ID}
        engagementId="e"
        canTriage
        myUserId={ME_ID}
        onClose={vi.fn()}
        calls={calls({ read })}
      />,
    );
    expect((await screen.findByRole("alert")).textContent).toContain("Could not load the team.");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Try again" })));
    expect(await screen.findByText("Fits our 2027 dairy programme.")).toBeTruthy();
  });

  it("closes with Close and says whether anything changed", async () => {
    const onClose = vi.fn();
    const c = calls();
    await sheet(c, { onClose });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Assign" })));
    await screen.findByText(/Assigned to/, { selector: "[role='status'], [role='alert'], div" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledWith(true);
  });
});

describe("the refusals by code", () => {
  it("maps each code, then the status", () => {
    const code = (c: string) => ({ detail: { code: c, message: "" } });
    expect(teamRefusal(403, code("role_not_allowed"))).toBe("notAllowed");
    expect(teamRefusal(422, code("invalid_assignee"))).toBe("invalidAssignee");
    expect(teamRefusal(409, code("unchanged"))).toBe("unchanged");
    expect(teamRefusal(409, code("conflict"))).toBe("conflict");
    expect(teamRefusal(429, code("too_many_assignments"))).toBe("tooMany");
    expect(teamRefusal(422, code("invalid_note"))).toBe("invalidNote");
    expect(teamRefusal(404, code("not_found"))).toBe("notFound");
    // A request-validation error is about the note only when the call sent one (the recommendation).
    const validation = { detail: [{ loc: ["body", "note"], msg: "x", type: "value_error" }] };
    expect(teamRefusal(422, validation, true)).toBe("invalidNote");
    expect(teamRefusal(422, validation)).toBe("generic");
    expect(teamRefusal(500, undefined)).toBe("generic");
  });
});

describe("Assigned to me", () => {
  it("reads ?assignee=me and matches the caller's own", () => {
    expect(assignedToMe("me")).toBe(true);
    expect(assignedToMe(["me"])).toBe(true);
    expect(assignedToMe(undefined)).toBe(false);
    expect(assignedToMe("someone")).toBe(false);
    expect(isAssignedTo(FACTS, SIGNATORY_ID)).toBe(true);
    expect(isAssignedTo(FACTS, ME_ID)).toBe(false);
    expect(isAssignedTo(null, ME_ID)).toBe(false);
  });

  it("is two links, the chosen one marked as current", async () => {
    const { container } = renderWithIntl(
      <>
        {await resolveServerTree(
          <AssigneeFilter mine allHref="/org/engagements" mineHref="/org/engagements?assignee=me" />,
        )}
      </>,
    );
    const nav = within(container).getByRole("navigation", { name: "Whose engagements" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href"), l.getAttribute("aria-current")])).toEqual([
      ["All", "/org/engagements", null],
      ["Assigned to me", "/org/engagements?assignee=me", "page"],
    ]);
  });
});
