import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { TeamCalls } from "../teams/calls";
import type { Peer, ProblemCard } from "../teams/teams";
import { PeerList } from "./PeerList";
import { TeamUpSheet } from "./TeamUpSheet";

// REQ-DEV-03 (P22-CF; D-58): the peers list's row states (Team up, then Invited with the line that takes focus; Block
// behind a confirmation, then the row leaves and a status line takes focus; More adds the next page) and the Team up
// sheet (one search field, one problem chosen, a note of up to 300 characters, Send invitation, each refusal in one
// sentence).

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

beforeAll(() => {
  // jsdom implements <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
afterEach(cleanup);

const NICHES = { "microfinance-saccos": "Microfinance & SACCOs", agriculture: "Agriculture" };

function peer(overrides: Partial<Peer> = {}): Peer {
  return {
    user_id: "01a11222-e68f-71fd-aa2e-f66d099bfab0",
    handle: "dev-kb3dysnk",
    headline: "Payments and USSD for SACCOs",
    county_name: "Nairobi City",
    shared_niches: ["microfinance-saccos", "agriculture"],
    same_county: true,
    ...overrides,
  };
}

const OTHER = peer({ user_id: "01a11222-e704-715c-94b6-403e7159f446", handle: "dev-5jtjq2m3", headline: null, same_county: false, shared_niches: ["agriculture"] });

function problem(id: string, title: string): ProblemCard {
  return { id, title, label: "Researched", niche: null, org: null, published_at: "2026-10-01T00:00:00Z", seeded_example: false, source: "research", statement: "x" } as unknown as ProblemCard;
}

const P1 = problem("01a11223-00af-7170-aa03-9bf3c39eef4a", "Tower sites go down when generators run dry");
const P2 = problem("01a11223-00af-7170-aa03-9bf3c39eef4b", "SACCO members miss loan repayments");

function fakeCalls(overrides: Partial<TeamCalls> = {}): Partial<TeamCalls> {
  return {
    problems: vi.fn(async (q: string) => (q ? [P2] : [P1, P2])),
    invite: vi.fn(async () => ({ ok: true as const })),
    block: vi.fn(async () => ({ ok: true as const })),
    peers: vi.fn(async () => ({ peers: [], next: null, opted_in: true })),
    ...overrides,
  };
}

function rowOf(handle: string) {
  return document.querySelector(`[data-peer="${handle}"]`) as HTMLElement;
}

describe("the peers list", () => {
  it("draws each peer by handle with headline, the niches shared by name and the county when it is theirs too", () => {
    renderWithIntl(<PeerList initial={{ peers: [peer(), OTHER], next: null, opted_in: true }} niches={NICHES} locale="en" calls={fakeCalls()} />);
    const first = rowOf("dev-kb3dysnk");
    expect(within(first).getByRole("heading", { name: "dev-kb3dysnk" })).toBeTruthy();
    expect(first.textContent).toContain("Payments and USSD for SACCOs");
    expect(first.textContent).toContain("Same county");
    expect(first.textContent).toContain("Shared niches: Microfinance & SACCOs and Agriculture");
    const second = rowOf("dev-5jtjq2m3");
    expect(second.textContent).toContain("No headline yet");
    expect(second.querySelector("[data-same-county]")).toBeNull();
    // One action per row, never the screen's primary one; Block sits in the overflow menu.
    expect(within(first).getAllByRole("button", { name: "Team up" })).toHaveLength(1);
    expect(document.querySelector("[data-primary]")).toBeNull();
    expect(first.querySelector("summary")?.getAttribute("aria-label")).toBe("More options");
    expect(first.querySelector("[data-peer-menu] [data-block]")?.textContent).toBe("Block");
  });

  it("Team up opens the sheet; once sent the row says Invited and the line takes focus", async () => {
    const calls = fakeCalls();
    renderWithIntl(<PeerList initial={{ peers: [peer()], next: null, opted_in: true }} niches={NICHES} locale="en" calls={calls} />);
    fireEvent.click(within(rowOf("dev-kb3dysnk")).getByRole("button", { name: "Team up" }));
    const sheet = await screen.findByRole("dialog", { name: "Team up with dev-kb3dysnk" });
    await within(sheet).findByRole("radio", { name: P1.title });
    fireEvent.click(within(sheet).getByRole("radio", { name: P1.title }));
    fireEvent.change(within(sheet).getByLabelText("Note (optional)"), { target: { value: "I can do the sensors." } });
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send invitation" })));
    expect(calls.invite).toHaveBeenCalledWith(peer().user_id, P1.id, "I can do the sensors.");
    const line = await screen.findByText("Invitation sent to dev-kb3dysnk.");
    const status = line.closest("[data-invited-line]") as HTMLElement;
    expect(status.textContent).toContain("Invited");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(within(rowOf("dev-kb3dysnk")).queryByRole("button", { name: "Team up" })).toBeNull();
    expect(rowOf("dev-kb3dysnk").hasAttribute("data-invited")).toBe(true);
  });

  it("Block asks first; once blocked the row leaves and a status line takes focus", async () => {
    const calls = fakeCalls();
    renderWithIntl(<PeerList initial={{ peers: [peer(), OTHER], next: null, opted_in: true }} niches={NICHES} locale="en" calls={calls} />);
    fireEvent.click(rowOf("dev-5jtjq2m3").querySelector("[data-block]") as HTMLElement);
    const dialog = screen.getByRole("dialog", { name: "Block dev-5jtjq2m3?" });
    expect(dialog.textContent).toContain(en.teamUp.block.body);
    expect(calls.block).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Block" })));
    expect(calls.block).toHaveBeenCalledWith(OTHER.user_id);
    expect(rowOf("dev-5jtjq2m3")).toBeNull();
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("dev-5jtjq2m3 is blocked. You no longer see each other anywhere.");
    await waitFor(() => expect(document.activeElement).toBe(status));
  });

  it("a failed block stays in the dialog with one sentence", async () => {
    renderWithIntl(
      <PeerList initial={{ peers: [peer()], next: null, opted_in: true }} niches={NICHES} locale="en" calls={fakeCalls({ block: vi.fn(async () => ({ ok: false as const })) })} />,
    );
    fireEvent.click(rowOf("dev-kb3dysnk").querySelector("[data-block]") as HTMLElement);
    const dialog = screen.getByRole("dialog", { name: "Block dev-kb3dysnk?" });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Block" })));
    expect(within(dialog).getByRole("alert").textContent).toBe(en.teamUp.block.failed);
    expect(rowOf("dev-kb3dysnk")).not.toBeNull();
  });

  it("More adds the next page; the hourly limit is said in one sentence", async () => {
    const peers = vi.fn(async () => ({ peers: [OTHER], next: 3, opted_in: true }));
    renderWithIntl(<PeerList initial={{ peers: [peer()], next: 2, opted_in: true }} niches={NICHES} locale="en" calls={fakeCalls({ peers })} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "More" })));
    expect(peers).toHaveBeenCalledWith(2);
    expect(rowOf("dev-5jtjq2m3")).not.toBeNull();
    peers.mockResolvedValueOnce("tooMany" as never);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "More" })));
    expect(screen.getByRole("alert").textContent).toBe(en.teamUp.list.moreTooMany);
  });
});

describe("the Team up sheet", () => {
  function open(calls: Partial<TeamCalls>, onDone = vi.fn()) {
    renderWithIntl(<TeamUpSheet peer={peer()} locale="en" calls={calls as TeamCalls} onDone={onDone} />);
    return { sheet: screen.getByRole("dialog", { name: "Team up with dev-kb3dysnk" }), onDone };
  }

  it("suggests the newest published problems, searches by words, and keeps the chosen one listed", async () => {
    const calls = fakeCalls();
    const { sheet } = open(calls);
    expect(document.activeElement).toBe(within(sheet).getByLabelText("Problem or Brief"));
    const group = await within(sheet).findByRole("group", { name: "Recently published" });
    fireEvent.click(within(group).getByRole("radio", { name: P1.title }));
    vi.useFakeTimers();
    try {
      fireEvent.change(within(sheet).getByLabelText("Problem or Brief"), { target: { value: "sacco" } });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(400);
      });
    } finally {
      vi.useRealTimers();
    }
    expect(calls.problems).toHaveBeenLastCalledWith("sacco");
    const results = await within(sheet).findByRole("group", { name: "Problems with those words" });
    expect(within(results).getAllByRole("radio").map((radio) => radio.getAttribute("value"))).toEqual([P1.id, P2.id]);
    expect((within(results).getByRole("radio", { name: P1.title }) as HTMLInputElement).checked).toBe(true);
  });

  it("asks for a problem first, and counts the note down near its 300 characters", async () => {
    const calls = fakeCalls();
    const { sheet } = open(calls);
    await within(sheet).findByRole("radio", { name: P1.title });
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send invitation" })));
    expect(within(sheet).getByRole("alert").textContent).toBe(en.teamUp.sheet.choose);
    expect(calls.invite).not.toHaveBeenCalled();
    fireEvent.change(within(sheet).getByLabelText("Note (optional)"), { target: { value: "x".repeat(299) } });
    expect(sheet.querySelector("[data-meter]")?.textContent).toBe("1 character left");
    fireEvent.change(within(sheet).getByLabelText("Note (optional)"), { target: { value: "x".repeat(302) } });
    expect(sheet.querySelector("[data-meter=over]")?.textContent).toBe("2 characters too many");
    fireEvent.click(within(sheet).getByRole("radio", { name: P1.title }));
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send invitation" })));
    expect(within(sheet).getByRole("alert").textContent).toBe(en.teamUp.refusal.noteTooLong);
    expect(calls.invite).not.toHaveBeenCalled();
  });

  it.each([
    ["peersOff", en.teamUp.refusal.peersOff],
    ["peerUnavailable", en.teamUp.refusal.peerUnavailable],
    ["problemUnavailable", en.teamUp.refusal.problemUnavailable],
    ["alreadyInvited", en.teamUp.refusal.alreadyInvited],
    ["tooMany", en.teamUp.refusal.tooMany],
  ] as const)("says the %s refusal in one sentence and stays open", async (refusal, sentence) => {
    const { sheet, onDone } = open(fakeCalls({ invite: vi.fn(async () => ({ ok: false as const, refusal })) }));
    fireEvent.click(await within(sheet).findByRole("radio", { name: P1.title }));
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send invitation" })));
    expect(within(sheet).getByRole("alert").textContent).toBe(sentence);
    expect(sheet.hasAttribute("open")).toBe(true);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("reports nothing sent when cancelled", async () => {
    const { sheet, onDone } = open(fakeCalls());
    await within(sheet).findByRole("radio", { name: P1.title });
    fireEvent.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(onDone).toHaveBeenCalledWith(false);
  });
});
