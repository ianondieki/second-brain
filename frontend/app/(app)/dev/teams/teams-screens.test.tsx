import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { StringTree } from "@/components/ClientStrings";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import TeamThreadPage from "./[id]/page";
import { STEP_STATUS_ID, STEPS_ID } from "./[id]/ids";
import { StepButtons } from "./[id]/StepButtons";
import { TeamThread } from "./[id]/TeamThread";
import type { TeamCalls } from "./calls";
import { Credits } from "./Credits";
import { InvitationList } from "./InvitationList";
import { StatusHost } from "./StatusHost";
import TeamsPage from "./page";
import { toThreadPage, type Invitation, type TeamThread as TeamThreadRead, type ThreadSummary } from "./teams";

// REQ-DEV-03 (P22-CF; D-58, D-62): /dev/teams (invitations received first with Accept and Decline, sent with
// Withdraw, each answer said in a status line that takes focus; threads open first; nothing at all is one sentence and
// one link), a team thread's page (open: the messages and Send as the one primary action, no files; closed: read-only
// with the reason's sentence) and its steps (credit the other developer on an idea; leave; block).

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }),
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, structuredClone((en as unknown as Record<string, StringTree>)[ns])])),
}));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
const state = vi.hoisted(() => ({
  side: "developer",
  invitations: { received: [], sent: [] } as { received: unknown[]; sent: unknown[] },
  threads: [] as unknown[],
  credits: [] as unknown[],
  thread: null as unknown,
  ideas: [] as unknown[],
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => ({ side: state.side, user: { id: "u1", display_name: "Amina" }, mfa: { enrolled: true }, memberships: [] }),
}));
vi.mock("./data", () => ({
  myInvitations: async () => state.invitations,
  myThreads: async () => state.threads,
  myContributions: async () => state.credits,
  teamThread: async () => state.thread,
  myPublishedIdeas: async () => state.ideas,
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => {
  refresh.mockReset();
  state.side = "developer";
  state.invitations = { received: [], sent: [] };
  state.threads = [];
  state.credits = [];
  state.ideas = [];
});
afterEach(cleanup);

const BRIAN = { user_id: "01a11222-e68f-71fd-aa2e-f66d099bfab0", handle: "dev-kb3dysnk", headline: null };
const PROBLEM = { id: "01a11223-00af-7170-aa03-9bf3c39eef4a", title: "Tower sites go down when generators run dry" };

function invitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: "01a11223-4000-7000-8000-000000000001",
    direction: "received",
    status: "pending",
    counterpart: BRIAN,
    problem: PROBLEM,
    note: "I build fuel sensors.\nShall we?",
    created_at: "2026-10-06T10:00:00+03:00",
    decided_at: null,
    ...overrides,
  };
}

function summary(overrides: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    id: "01a11223-32cd-732d-9755-f7206d3c33e4",
    counterpart: BRIAN,
    problem: PROBLEM,
    created_at: "2026-10-06T10:00:00+03:00",
    last_message_at: "2026-10-06T12:00:00+03:00",
    unread: 0,
    open: true,
    closed_at: null,
    closed_reason: null,
    ...overrides,
  };
}

function read(overrides: Partial<ThreadSummary> = {}, items: TeamThreadRead["items"] = []): TeamThreadRead {
  const thread = summary(overrides);
  return { thread, can_post: thread.open, max_chars: 4000, last_read_at: null, items, next_cursor: null };
}

const MESSAGES: TeamThreadRead["items"] = [
  { id: "01a11223-5000-7000-8000-000000000001", mine: true, body: "Thanks for joining.", redacted: false, created_at: "2026-10-06T11:00:00+03:00" },
  { id: "01a11223-5000-7000-8000-000000000002", mine: false, body: "Happy to help.", redacted: false, created_at: "2026-10-06T12:00:00+03:00" },
];

function teamCalls(overrides: Partial<TeamCalls> = {}): Partial<TeamCalls> {
  return {
    accept: vi.fn(async () => ({ ok: true as const, threadId: "01a11223-32cd-732d-9755-f7206d3c33e4" })),
    decline: vi.fn(async () => ({ ok: true as const })),
    withdraw: vi.fn(async () => ({ ok: true as const })),
    leave: vi.fn(async () => ({ ok: true as const })),
    block: vi.fn(async () => ({ ok: true as const })),
    credit: vi.fn(async () => ({ ok: true as const })),
    leaveCredit: vi.fn(async () => ({ ok: true as const })),
    ...overrides,
  };
}

describe("the invitations", () => {
  it("lists received ones first with Accept and Decline, sent ones with Withdraw, and no primary action", () => {
    const sent = invitation({ id: "01a11223-4000-7000-8000-000000000002", direction: "sent", note: null, counterpart: { ...BRIAN, handle: "dev-5jtjq2m3" } });
    renderWithIntl(<StatusHost><InvitationList initial={{ received: [invitation()], sent: [sent] }} calls={teamCalls()} /></StatusHost>);
    const lists = document.querySelectorAll("[data-invitations]");
    expect([...lists].map((list) => list.getAttribute("data-invitations"))).toEqual(["received", "sent"]);
    const card = within(lists[0] as HTMLElement).getByRole("article", { name: "dev-kb3dysnk invited you" });
    expect(card.textContent).toContain("On Tower sites go down when generators run dry");
    expect(card.querySelector("[data-note]")?.textContent).toBe("I build fuel sensors.\nShall we?");
    expect(within(card).getAllByRole("button").map((b) => b.textContent)).toEqual(["Accept", "Decline"]);
    const mine = within(lists[1] as HTMLElement).getByRole("article", { name: "You invited dev-5jtjq2m3" });
    expect(within(mine).getAllByRole("button").map((b) => b.textContent)).toEqual(["Withdraw"]);
    expect(document.querySelector("[data-primary]")).toBeNull();
  });

  it("Accept says the thread is open above the sections, links it, takes focus and reads the page again", async () => {
    const calls = teamCalls();
    renderWithIntl(<StatusHost><InvitationList initial={{ received: [invitation()], sent: [] }} calls={calls} /></StatusHost>);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Accept" })));
    expect(calls.accept).toHaveBeenCalledWith(invitation().id);
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Invitation accepted. Your thread with dev-kb3dysnk is open.");
    expect(within(status).getByRole("link", { name: "Open the thread" }).getAttribute("href")).toBe("/dev/teams/01a11223-32cd-732d-9755-f7206d3c33e4");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(document.querySelector("[data-invitation]")).toBeNull();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("Decline and Withdraw say so; an invitation already answered says that instead", async () => {
    const sent = invitation({ id: "01a11223-4000-7000-8000-000000000002", direction: "sent" });
    const calls = teamCalls({ withdraw: vi.fn(async () => ({ ok: false as const, refusal: "gone" as const })) });
    renderWithIntl(<StatusHost><InvitationList initial={{ received: [invitation()], sent: [sent] }} calls={calls} /></StatusHost>);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Decline" })));
    expect(screen.getByRole("status").textContent).toBe("Invitation declined.");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Withdraw" })));
    expect(screen.getByRole("alert").textContent).toBe(en.teamUp.invitation.gone);
    expect(document.querySelector("[data-invitation]")).toBeNull();
  });
});

describe("/dev/teams", () => {
  async function open() {
    return render(await resolveServerTree(await TeamsPage()));
  }

  it("with nothing at all: one sentence and one link to Peers", async () => {
    await open();
    const empty = document.querySelector("[data-teams=empty]") as HTMLElement;
    expect(empty.textContent).toContain(en.teams.list.empty);
    expect(within(empty).getByRole("link", { name: "Find peers" }).getAttribute("href")).toBe("/dev/peers");
    expect(document.querySelector("[data-primary]")).toBeNull();
  });

  it("lists open threads first, with the problem, the last message's time and unread in words", async () => {
    state.threads = [
      summary({ id: "01a11223-32cd-732d-9755-f7206d3c33e1", open: false, closed_reason: "left", last_message_at: "2026-10-06T15:00:00+03:00" }),
      summary({ unread: 2 }),
    ];
    await open();
    const rows = document.querySelectorAll("[data-thread]");
    expect([...rows].map((row) => row.getAttribute("data-open"))).toEqual(["true", "false"]);
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "dev-kb3dysnk" }).getAttribute("href")).toBe(
      "/dev/teams/01a11223-32cd-732d-9755-f7206d3c33e4",
    );
    expect(rows[0].textContent).toContain("On Tower sites go down when generators run dry");
    expect(rows[0].textContent).toContain("Last message 6 Oct 2026, 12:00");
    expect(rows[0].querySelector("[data-unread]")?.textContent).toBe("2 unread");
    expect(rows[1].querySelector("[data-closed]")?.textContent).toBe("Closed");
  });

  it("sends an organisation member to their own home", async () => {
    state.side = "org";
    await expect(TeamsPage()).rejects.toThrow("redirect:/org");
  });
});

describe("a team thread's page", () => {
  async function open() {
    const node = await TeamThreadPage({ params: Promise.resolve({ id: summary().id }) } as never);
    return render(await resolveServerTree(node));
  }

  it("open: the problem links, the messages are drawn, Send is the one primary action and there are no files", async () => {
    state.thread = read({ unread: 0 }, MESSAGES);
    state.ideas = [{ id: "i1", title: "Fuel-level alerts" }];
    await open();
    expect(screen.getByRole("heading", { level: 1, name: "dev-kb3dysnk" })).toBeTruthy();
    expect(screen.getByRole("link", { name: PROBLEM.title }).getAttribute("href")).toBe(`/problems/${PROBLEM.id}`);
    expect(document.querySelectorAll("[data-message]")).toHaveLength(2);
    expect(document.querySelector('[data-message][data-mine="false"]')?.textContent).toContain("dev-kb3dysnk");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(document.querySelector("[data-primary]")?.textContent).toBe("Send");
    expect(document.querySelector("[data-attach]")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Report" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Add as contributor on an idea" })).toBeTruthy();
    expect(document.querySelector("[data-thread-closed]")).toBeNull();
  });

  it.each([
    ["left", en.teams.thread.closed.left],
    ["blocked", en.teams.thread.closed.blocked],
    [null, en.teams.thread.closed.ended],
  ] as const)("closed (%s): read-only, no composer, the reason in one sentence", async (reason, sentence) => {
    state.thread = read({ open: false, closed_reason: reason, closed_at: "2026-10-06T13:00:00+03:00" }, MESSAGES);
    await open();
    expect(document.querySelectorAll("[data-message]")).toHaveLength(2);
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelector("[data-primary]")).toBeNull();
    expect(document.querySelector("[data-thread-closed]")?.textContent).toBe(sentence);
    expect(screen.queryByRole("button", { name: "Leave thread" })).toBeNull();
  });

  it("closed for good with no one to see: no steps but reading", async () => {
    state.thread = read({ open: false, closed_reason: "ended", counterpart: null }, []);
    await open();
    expect(screen.getByRole("heading", { level: 1, name: "A developer" })).toBeTruthy();
    expect(document.querySelectorAll("[data-thread-actions] button, [data-thread-actions] summary")).toHaveLength(0);
    expect(document.querySelector("[data-thread-closed]")?.textContent).toBe(en.teams.thread.closedEmpty);
  });
});

describe("the thread's steps", () => {
  const IDEAS = [
    { id: "01a11223-0050-70b5-b1ae-6aba07659960", title: "Fuel-level alerts for off-grid tower sites" },
    { id: "01a11223-2bee-7111-ad0b-928eac1174b2", title: "Clear loan-fee statements" },
  ];

  // As the page draws them: the buttons are markup under #thread-steps, TeamThread answers their presses.
  function steps(ideas: typeof IDEAS, calls: Partial<TeamCalls>) {
    return (
      <>
        <div id={STEP_STATUS_ID} className="contents" />
        <div id={STEPS_ID}>
          <StepButtons
            credit={ideas.length > 0 ? "Add as contributor on an idea" : null}
            more="More options"
            leave="Leave thread"
            block="Block dev-kb3dysnk"
          />
        </div>
        <TeamThread
          threadId={summary().id}
          initial={toThreadPage(read({}, MESSAGES), "dev-kb3dysnk")}
          counterpart="dev-kb3dysnk"
          today="2026-10-06"
          locale="en"
          empty={null}
          person={BRIAN}
          ideas={ideas}
          calls={calls}
        />
      </>
    );
  }

  it("credits the other developer on the chosen idea and says so", async () => {
    const calls = teamCalls();
    renderWithIntl(steps(IDEAS, calls));
    fireEvent.click(screen.getByRole("button", { name: "Add as contributor on an idea" }));
    const sheet = await screen.findByRole("dialog", { name: "Add dev-kb3dysnk as a contributor" });
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Add contributor" })));
    expect(within(sheet).getByRole("alert").textContent).toBe(en.teamUp.credit.choose);
    fireEvent.click(within(sheet).getByRole("radio", { name: IDEAS[0].title }));
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Add contributor" })));
    expect(calls.credit).toHaveBeenCalledWith(IDEAS[0].id, BRIAN.user_id);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe(`Added as contributor on ${IDEAS[0].title}.`);
    await waitFor(() => expect(document.activeElement).toBe(status));
  });

  it("says a credit given before in one sentence", async () => {
    renderWithIntl(steps(IDEAS, teamCalls({ credit: vi.fn(async () => ({ ok: false as const, refusal: "already" as const })) })));
    fireEvent.click(screen.getByRole("button", { name: "Add as contributor on an idea" }));
    const sheet = await screen.findByRole("dialog", { name: "Add dev-kb3dysnk as a contributor" });
    fireEvent.click(within(sheet).getByRole("radio", { name: IDEAS[1].title }));
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Add contributor" })));
    expect(within(sheet).getByRole("alert").textContent).toBe(en.teamUp.credit.already);
  });

  it("Leave and Block each ask first, then say so and read the page again", async () => {
    const calls = teamCalls();
    renderWithIntl(steps([], calls));
    expect(screen.queryByRole("button", { name: "Add as contributor on an idea" })).toBeNull();
    fireEvent.click(document.querySelector("[data-leave]") as HTMLElement);
    const leave = await screen.findByRole("dialog", { name: "Leave this thread?" });
    await act(async () => fireEvent.click(within(leave).getByRole("button", { name: "Leave" })));
    expect(calls.leave).toHaveBeenCalledWith(summary().id);
    expect(screen.getByRole("status").textContent).toBe(en.teamUp.thread.left);
    fireEvent.click(document.querySelector("[data-block]") as HTMLElement);
    const block = await screen.findByRole("dialog", { name: "Block dev-kb3dysnk?" });
    await act(async () => fireEvent.click(within(block).getByRole("button", { name: "Block" })));
    expect(calls.block).toHaveBeenCalledWith(BRIAN.user_id);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("dev-kb3dysnk is blocked. You no longer see each other anywhere.");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});

describe("credits", () => {
  it("Leave asks first, then the credit leaves the list and a status line says so", async () => {
    const calls = teamCalls();
    const credit = { proposal_id: "01a11223-0050-70b5-b1ae-6aba07659960", title: "Fuel-level alerts", added_at: "2026-10-06T10:00:00+03:00" };
    renderWithIntl(<Credits initial={[credit, { ...credit, proposal_id: "x", title: null }]} calls={calls} />);
    const items = document.querySelectorAll("[data-credit]");
    expect(items[0].textContent).toContain("You are a contributor on Fuel-level alerts");
    expect(items[1].textContent).toContain("You are a contributor on An idea that is not published now");
    fireEvent.click(within(items[0] as HTMLElement).getByRole("button", { name: "Leave" }));
    const dialog = screen.getByRole("dialog", { name: "Stop being a contributor on Fuel-level alerts?" });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Leave" })));
    expect(calls.leaveCredit).toHaveBeenCalledWith(credit.proposal_id);
    expect(document.querySelectorAll("[data-credit]")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe("You are no longer a contributor on Fuel-level alerts.");
  });
});
