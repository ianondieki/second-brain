import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { Pitches } from "../Pitches";
import { WhoHasSeen } from "../WhoHasSeen";
import { WithdrawTag } from "../WithdrawTag";
import type { PitchOutcome } from "./calls";
import { PitchForm, type PickerGroup, type PickerRow, type PitchFormProps } from "./PitchForm";
import type { MyTags, PitchResult, ProposalViews, TagOut } from "./picker";

// REQ-PROP-03 (F2 picker), REQ-DIR-04 (held tags), REQ-PROV-03 ("Who has seen this"): the picker's choices and cap,
// every refusal as one sentence and at most one action, what was sent and saved, the idea's tags with Withdraw, and
// the owner's view log (docs/spec/07 items 2, 4 and 6).

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));
// The server sections read next-intl on the server; here they read the English catalogue the same way.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));

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

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

const PROPOSAL = "0199a000-0000-7000-8000-0000000000aa";
const SAFCELL = "0199a000-0000-7000-8000-00000000000a";
const TELMARK = "0199a000-0000-7000-8000-00000000000b";
const AIRWAVE = "0199a000-0000-7000-8000-00000000000c";
const OWN = "0199a000-0000-7000-8000-00000000000d";
const ELSEWHERE = "0199a000-0000-7000-8000-00000000000e";

function row(id: string, name: string, outcome: ReactNode): PickerRow {
  return { id, name, available: true, about: <p data-about="">{`Company, Nairobi City (${name})`}</p>, outcome };
}

/** A choice made in another search, resolved by id on the server and shown by name in the "chosen" group. */
const CHOSEN_ELSEWHERE = row(ELSEWHERE, "Elsewhere Ltd", <p data-outcome="sent">Gets it now</p>);

const GROUPS: PickerGroup[] = [
  {
    key: "ict",
    parent: "ICT",
    name: "Networks & Telecommunications",
    rows: [
      row(SAFCELL, "Safcell", <p data-outcome="sent">Gets it now</p>),
      row(TELMARK, "Telmark", <p data-outcome="saved">Saved until they verify</p>),
      row(AIRWAVE, "Airwave", <p data-outcome="saved">Saved until they verify</p>),
      { ...row(OWN, "Own Co", <p data-reason="own_organisation">You are a member</p>), available: false },
    ],
  },
];

function renderForm(overrides: Partial<PitchFormProps> = {}) {
  const props: PitchFormProps = {
    proposalId: PROPOSAL,
    ideaHref: `/dev/ideas/${PROPOSAL}`,
    cap: { used: 2, limit: 5, plan: "dev_free" },
    groups: GROUPS,
    initialSelected: [],
    filters: <input aria-label="Search by name, niche or county" name="q" />,
    narrowed: false,
    ...overrides,
  };
  return renderWithIntl(<PitchForm {...props} />);
}

function tag(overrides: Partial<TagOut> = {}): TagOut {
  return {
    id: "0199a000-0000-7000-8000-0000000000f1",
    org: { id: SAFCELL, name: "Safcell", slug: "safcell", badge: { level: "e2", text: "Legal entity verified" } },
    status: "delivered",
    open: true,
    created_at: "2026-09-29T08:00:00Z",
    engagement_id: null,
    message: null,
    ...overrides,
  };
}

async function pitchWith(outcome: PitchOutcome) {
  const pitchImpl = vi.fn(async () => outcome);
  return pitchImpl;
}

function box(name: string) {
  return screen.getByRole("checkbox", { name }) as HTMLInputElement;
}

async function clickPitch() {
  await act(async () => {
    fireEvent.click(document.querySelector("[data-intent='pitch']")!);
  });
}

describe("the picker", () => {
  it("shows the plan cap as pitches left and what one pitch may hold", () => {
    renderForm();
    expect(screen.getByText("3 of 5 pitches left for this idea on your plan.")).toBeTruthy();
    expect(screen.getByText("0 of 3 chosen")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Networks & Telecommunications$/ })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("says when the plan has no limit, and then allows one batch of 20", () => {
    renderForm({ cap: { used: 40, limit: null, plan: "dev_pro" } });
    expect(screen.getByText("Your plan has no limit on pitches for this idea.")).toBeTruthy();
    expect(screen.getByText("0 of 20 chosen")).toBeTruthy();
  });

  it("counts choices and stops at the cap: other rows lock and say why", () => {
    renderForm({ cap: { used: 3, limit: 5, plan: "dev_free" } });
    fireEvent.click(box("Safcell"));
    expect(screen.getByText("1 of 2 chosen")).toBeTruthy();
    fireEvent.click(box("Telmark"));
    expect(screen.getByText("2 of 2 chosen")).toBeTruthy();
    expect(screen.getByText("That is all the pitches your plan has left for this idea.")).toBeTruthy();
    expect(box("Airwave").disabled).toBe(true);
    expect(box("Safcell").disabled).toBe(false); // a chosen one can still be unticked
    fireEvent.click(box("Safcell"));
    expect(box("Airwave").disabled).toBe(false);
  });

  it("never lets an unavailable organisation be chosen", () => {
    renderForm();
    expect(box("Own Co").disabled).toBe(true);
    expect(screen.getByText("You are a member")).toBeTruthy();
  });

  it("shows choices from other searches first, by name with their outcome, and sends them with the ones here", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "network", conflicts: [] });
    const { container } = renderForm({ initialSelected: [SAFCELL, ELSEWHERE], chosen: [CHOSEN_ELSEWHERE], pitchImpl });
    const chosen = container.querySelector("[data-chosen-group]") as HTMLElement;
    expect(within(chosen).getByRole("heading", { name: "Chosen in other searches" })).toBeTruthy();
    expect((within(chosen).getByRole("checkbox", { name: "Elsewhere Ltd" }) as HTMLInputElement).checked).toBe(true);
    expect(within(chosen).getByText("Gets it now")).toBeTruthy();
    expect(container.querySelector("input[type=hidden]")).toBeNull(); // nothing chosen out of sight
    expect(box("Safcell").checked).toBe(true);
    expect(screen.getByText("2 of 3 chosen")).toBeTruthy();
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledWith(PROPOSAL, [SAFCELL, ELSEWHERE]);
    expect(screen.getByRole("alert").textContent).toBe(
      "We could not reach the server, so nothing was sent. Check your connection; your choices stay on this page.",
    );
    expect(box("Safcell").checked).toBe(true); // nothing is lost
  });

  it("asks for a choice before pitching", async () => {
    const pitchImpl = vi.fn();
    renderForm({ pitchImpl });
    await clickPitch();
    expect(pitchImpl).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("Choose at least one company to pitch to.");
  });

  it("offers to clear a search, keeping the choices", () => {
    renderForm({ narrowed: true, initialSelected: [TELMARK] });
    expect(screen.getByRole("link", { name: "Clear search" }).getAttribute("href")).toBe(
      `/dev/ideas/${PROPOSAL}/pitch?sel=${TELMARK}`,
    );
  });

  it("pages with the choices, as part of the same form", () => {
    renderForm({ cursor: "c1", nextCursor: "c2" });
    const pages = within(screen.getByRole("navigation", { name: "Pages" }));
    expect((pages.getByRole("button", { name: "Next page" }) as HTMLButtonElement).value).toBe("c2");
    expect((pages.getByRole("button", { name: "First page" }) as HTMLButtonElement).value).toBe("");
  });
});

describe("what the picker sends", () => {
  it("never sends a crafted choice the page does not show by name (MAJOR 1)", async () => {
    // /dev/ideas/<id>/pitch?q=Safcell&sel=<an E2 organisation the developer never saw>: the server could not show it.
    const pitchImpl = await pitchWith({ ok: false, problem: "failed", conflicts: [] });
    const { container } = renderForm({ initialSelected: [ELSEWHERE], pitchImpl });
    expect(screen.getByText("0 of 3 chosen")).toBeTruthy();
    expect(container.querySelector(`input[value="${ELSEWHERE}"]`)).toBeNull();
    fireEvent.click(box("Safcell"));
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledWith(PROPOSAL, [SAFCELL]);
  });

  it("compares ids in one case: an upper-case card id still matches its choice, and goes out in lower case", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "failed", conflicts: [] });
    const upper = [{ ...GROUPS[0], rows: [row(SAFCELL.toUpperCase(), "Safcell", null)] }];
    renderForm({ groups: upper, initialSelected: [SAFCELL], pitchImpl });
    expect(box("Safcell").checked).toBe(true);
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledWith(PROPOSAL, [SAFCELL]);
  });


  it("never sends an organisation the page shows as unavailable, even when the URL chose it", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "failed", conflicts: [] });
    renderForm({ initialSelected: [OWN, SAFCELL], pitchImpl });
    expect(box("Own Co").checked).toBe(false);
    expect(box("Own Co").disabled).toBe(true);
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledWith(PROPOSAL, [SAFCELL]);
  });

  it("never sends more than the plan's pitches left, whatever the URL holds", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "failed", conflicts: [] });
    renderForm({ cap: { used: 4, limit: 5, plan: "dev_free" }, initialSelected: [SAFCELL, TELMARK, ELSEWHERE], pitchImpl });
    expect(screen.getByText("1 of 1 chosen")).toBeTruthy();
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledWith(PROPOSAL, [SAFCELL]);
  });

  it("sends each organisation once, in lower case, and nothing for a refused one after a 409", async () => {
    const pitchImpl = vi
      .fn<(id: string, orgs: string[]) => Promise<PitchOutcome>>()
      .mockResolvedValueOnce({ ok: false, problem: "conflict", conflicts: [{ orgId: TELMARK, reason: "tagged" }] })
      .mockResolvedValueOnce({ ok: false, problem: "failed", conflicts: [] });
    renderForm({ initialSelected: [SAFCELL.toUpperCase(), SAFCELL, TELMARK], pitchImpl });
    await clickPitch();
    expect(pitchImpl).toHaveBeenLastCalledWith(PROPOSAL, [SAFCELL, TELMARK]);
    fireEvent.click(box("Telmark")); // locked: the 409 said why
    await clickPitch();
    expect(pitchImpl).toHaveBeenLastCalledWith(PROPOSAL, [SAFCELL]);
  });

  it("sends nothing while a pitch is under way", async () => {
    let settle: (value: PitchOutcome) => void = () => {};
    const pitchImpl = vi.fn(() => new Promise<PitchOutcome>((resolve) => (settle = resolve)));
    renderForm({ initialSelected: [SAFCELL], pitchImpl });
    await clickPitch();
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledTimes(1);
    expect(box("Telmark").disabled).toBe(true);
    await act(async () => settle({ ok: false, problem: "failed", conflicts: [] }));
    expect(box("Telmark").disabled).toBe(false);
  });
});

describe("the picker's wording and state", () => {
  it("words the lead and the limit by what stops more choices: the plan, or one pitch's batch", () => {
    renderForm({ cap: { used: 3, limit: 5, plan: "dev_free" } });
    expect(screen.getByText(/^Choose companies, up to 2 for this pitch\. Fully verified companies get your idea now\./)).toBeTruthy();
    cleanup();
    const many = Array.from({ length: 20 }, (_, i) => row(`0199a000-0000-7000-8000-${String(i + 100).padStart(12, "0")}`, `Org ${i}`, null));
    renderForm({ cap: { used: 0, limit: null, plan: "dev_pro" }, groups: [{ key: "g", name: "G", rows: many }], initialSelected: many.map((r) => r.id) });
    expect(screen.getByText(/^Choose companies, up to 20 for this pitch\./)).toBeTruthy();
    expect(screen.getByText("That is the most one pitch can hold. Pitch these, then choose more.")).toBeTruthy();
  });

  it("keeps the search, niche, paging and Clear search still while a pitch is under way", async () => {
    let settle: (value: PitchOutcome) => void = () => {};
    const pitchImpl = vi.fn(() => new Promise<PitchOutcome>((resolve) => (settle = resolve)));
    renderForm({ initialSelected: [SAFCELL], pitchImpl, narrowed: true, cursor: "c1", nextCursor: "c2" });
    await clickPitch();
    expect((screen.getByLabelText("Search by name, niche or county") as HTMLInputElement).matches(":disabled")).toBe(true);
    expect((screen.getByRole("button", { name: "Next page" }) as HTMLButtonElement).matches(":disabled")).toBe(true);
    const clear = screen.getByText("Clear search");
    expect(clear.getAttribute("href")).toBeNull();
    expect(clear.getAttribute("aria-disabled")).toBe("true");
    await act(async () => settle({ ok: false, problem: "failed", conflicts: [] }));
    expect((screen.getByLabelText("Search by name, niche or county") as HTMLInputElement).matches(":disabled")).toBe(false);
    expect(screen.getByRole("link", { name: "Clear search" })).toBeTruthy();
  });

  it("keeps the sticky bar to the summary and Pitch", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "failed", conflicts: [] });
    renderForm({ cap: { used: 3, limit: 5, plan: "dev_free" }, initialSelected: [SAFCELL, TELMARK], pitchImpl });
    await clickPitch();
    const bar = document.querySelector("[data-action-bar]") as HTMLElement;
    expect(bar.querySelector("[role=alert], [role=status], [data-max-reached]")).toBeNull();
    expect(within(bar).getByText("2 of 2 chosen")).toBeTruthy();
    expect(within(bar).getAllByRole("button")).toHaveLength(1);
  });
});

describe("a refused pitch", () => {
  it("unticks the organisations of a 409 and puts the reason by each", async () => {
    const pitchImpl = await pitchWith({
      ok: false,
      problem: "conflict",
      conflicts: [
        { orgId: TELMARK, reason: "open_elsewhere" },
        { orgId: ELSEWHERE, reason: "cooldown" },
      ],
    });
    renderForm({ initialSelected: [SAFCELL, TELMARK, ELSEWHERE], chosen: [CHOSEN_ELSEWHERE], pitchImpl });
    await clickPitch();
    expect(screen.getByRole("alert").textContent).toBe(
      "Nothing was sent: 2 of the companies you chose cannot be pitched to now, so they are unticked with the reason by each.",
    );
    expect(box("Telmark").checked).toBe(false);
    expect(box("Telmark").disabled).toBe(true);
    expect(screen.getByText(/You have an open pitch with Telmark from another idea/)).toBeTruthy();
    expect(box("Safcell").checked).toBe(true);
    expect(screen.getByText("1 of 3 chosen")).toBeTruthy(); // the chosen one elsewhere is unticked too
    expect(screen.getByText(/Elsewhere Ltd declined a pitch of yours/)).toBeTruthy();
    // The refused row keeps its type, county and badge, with the reason below them.
    const telmark = document.querySelector(`[data-org-row="${TELMARK}"]`) as HTMLElement;
    expect(within(telmark).getByText("Company, Nairobi City (Telmark)")).toBeTruthy();
    expect(telmark.querySelector("[data-outcome]")).toBeNull();
    // The alert is in the page's flow above the list, not in the sticky bar, and takes focus.
    const alert = screen.getByRole("alert");
    expect(alert.closest("[data-action-bar]")).toBeNull();
    expect(document.activeElement).toBe(alert);
  });

  it("unticks the organisations a 404 says left the directory", async () => {
    const pitchImpl = await pitchWith({ ok: false, problem: "orgsGone", conflicts: [], gone: [TELMARK] });
    renderForm({ initialSelected: [SAFCELL, TELMARK], pitchImpl });
    await clickPitch();
    expect(box("Telmark").checked).toBe(false);
    expect(box("Telmark").disabled).toBe(true);
    expect(screen.getByText("Telmark is no longer listed, so it was unticked.")).toBeTruthy();
    expect(box("Safcell").checked).toBe(true);
  });

  it("takes the plan's cap from a 402 and sends nothing more until the choices fit", async () => {
    const pitchImpl = vi.fn(async (): Promise<PitchOutcome> => ({
      ok: false,
      problem: "planLimit",
      conflicts: [],
      limit: 5,
      used: 4,
    }));
    renderForm({ initialSelected: [SAFCELL, TELMARK], pitchImpl });
    await clickPitch();
    expect(screen.getByText("1 of 5 pitches left for this idea on your plan.")).toBeTruthy();
    expect(screen.getByText("2 of 1 chosen")).toBeTruthy();
    expect(box("Airwave").disabled).toBe(true);
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledTimes(1); // refused here, without asking again
    fireEvent.click(box("Telmark"));
    await clickPitch();
    expect(pitchImpl).toHaveBeenCalledTimes(2);
    expect(pitchImpl).toHaveBeenLastCalledWith(PROPOSAL, [SAFCELL]);
  });

  it.each([
    [{ problem: "planLimit", limit: 5, used: 4 }, "Your plan has 1 of 5 pitches left for this idea, so nothing was sent: choose fewer companies.", null],
    [{ problem: "planLimitUnknown" }, "Your plan allows no more pitches for this idea, so nothing was sent.", null],
    [
      { problem: "d1Required" },
      "Pitching needs a verified mobile number on your account, which you cannot add in the app yet, so nothing was sent.",
      null,
    ],
    [{ problem: "notPublic" }, "This idea is not published and clear of review, so nothing was sent.", "Back to your idea"],
    [{ problem: "orgsGone" }, "Some companies you chose are no longer listed, so nothing was sent. Reload the list, then choose again.", "Reload the list"],
    [{ problem: "changed" }, "Something changed while you were choosing, so nothing was sent: reload the list and try again.", "Reload the list"],
    [{ problem: "signedOut" }, "Your session has ended, so nothing was sent. Log in again, then pitch.", "Log in"],
    [{ problem: "failed" }, "Something went wrong, so nothing was sent. Try again in a moment.", null],
  ] as const)("%o reads as one sentence and at most one action", async (refusal, sentence, action) => {
    const pitchImpl = await pitchWith({ ok: false, conflicts: [], ...refusal } as PitchOutcome);
    renderForm({ initialSelected: [SAFCELL], pitchImpl });
    await clickPitch();
    const alert = screen.getByRole("alert");
    expect(alert.querySelector("p")?.textContent).toBe(sentence);
    const links = within(alert).queryAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(action ? [action] : []);
  });
});

describe("a plan limit (REQ-BIL-08)", () => {
  it.each([
    [{ problem: "planLimit", limit: 5, used: 5, upgrade: "dev_pro_monthly" }],
    [{ problem: "planLimitUnknown", upgrade: "dev_pro_monthly" }],
  ] as const)("%o links to the next plan up and back to this picker", async (refusal) => {
    const pitchImpl = await pitchWith({ ok: false, conflicts: [], ...refusal } as PitchOutcome);
    renderForm({ initialSelected: [SAFCELL], pitchImpl });
    await clickPitch();
    const links = within(screen.getByRole("alert")).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Upgrade your plan"]);
    expect(links[0].getAttribute("href")).toBe(
      `/billing/upgrade?plan=dev_pro_monthly&next=${encodeURIComponent(`/dev/ideas/${PROPOSAL}/pitch`)}`,
    );
  });
});

describe("after a pitch", () => {
  const RESULT: PitchResult = {
    tags: [
      tag(),
      tag({
        id: "0199a000-0000-7000-8000-0000000000f2",
        org: { id: TELMARK, name: "Telmark", slug: "telmark", badge: { level: "e0", text: "Listed" } },
        status: "held_unclaimed",
      }),
      tag({
        id: "0199a000-0000-7000-8000-0000000000f3",
        org: { id: AIRWAVE, name: "Airwave", slug: "airwave", badge: { level: "e1", text: "Verifying" } },
        status: "held_pending_verification",
      }),
    ],
    sent_count: 1,
    saved_count: 2,
    email_sent: true,
    cap: { used: 5, limit: 5, plan: "dev_free" },
  };

  it("shows what was sent now and what is saved, with the held sentences, and one primary action", async () => {
    const pitchImpl = await pitchWith({ ok: true, value: RESULT });
    renderForm({ initialSelected: [SAFCELL, TELMARK, AIRWAVE], pitchImpl });
    await clickPitch();
    const heading = screen.getByRole("heading", { name: "Pitched" });
    expect(document.activeElement).toBe(heading);
    expect(screen.getByRole("heading", { name: "Sent now (1)" }).querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Saved until they verify (2)" }).querySelector("svg")).not.toBeNull();
    expect(
      screen.getByText(
        "Telmark isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify. We don't email them on your behalf.",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Airwave is still verifying its details. Your proposal is saved and they'll see it once they are verified."),
    ).toBeTruthy();
    expect(screen.getByText("A record of this pitch goes to your email address.")).toBeTruthy();
    expect(screen.getByText("0 of 5 pitches left for this idea on your plan.")).toBeTruthy();
    const primary = document.querySelectorAll("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Back to your idea");
    expect(screen.getByRole("link", { name: "Pitch to another company" }).getAttribute("href")).toBe(
      `/dev/ideas/${PROPOSAL}/pitch`,
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("does not mention the email when nothing reached an organisation", async () => {
    const saved = { ...RESULT, tags: RESULT.tags.slice(1), sent_count: 0, email_sent: false };
    const pitchImpl = await pitchWith({ ok: true, value: saved });
    renderForm({ initialSelected: [TELMARK, AIRWAVE], pitchImpl });
    await clickPitch();
    expect(screen.queryByRole("heading", { name: /Sent now/ })).toBeNull();
    expect(screen.queryByText("A record of this pitch goes to your email address.")).toBeNull();
  });
});

describe("withdrawing a saved pitch", () => {
  it("asks first, then withdraws and refreshes the list", async () => {
    const withdrawImpl = vi.fn(async () => ({ ok: true as const, value: tag({ status: "withdrawn", open: false }) }));
    renderWithIntl(
      <>
        <h2 id="pitches-heading" tabIndex={-1}>
          Pitches
        </h2>
        <WithdrawTag proposalId={PROPOSAL} tagId="t1" orgName="Telmark" returnFocusTo="pitches-heading" withdrawImpl={withdrawImpl} />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    const dialog = screen.getByRole("dialog", { name: "Withdraw this pitch?" });
    expect(dialog.textContent).toContain("Telmark has not seen it.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(withdrawImpl).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    });
    expect(withdrawImpl).toHaveBeenCalledWith(PROPOSAL, "t1");
    expect(refresh).toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("pitches-heading");
    expect(dialog.hasAttribute("open")).toBe(false);
  });

  it("stays open with the reason when the pitch already reached the company", async () => {
    const withdrawImpl = vi.fn(async () => ({ ok: false as const, problem: "delivered" as const }));
    renderWithIntl(
      <WithdrawTag proposalId={PROPOSAL} tagId="t1" orgName="Telmark" returnFocusTo="x" withdrawImpl={withdrawImpl} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    });
    expect(screen.getByRole("alert").textContent).toBe(
      "This pitch already reached the company, so it cannot be withdrawn here.",
    );
    expect(refresh).toHaveBeenCalled(); // the list behind the dialog catches up
    // Opened again, the dialog starts without the old reason.
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the list as it is after a failure it can retry", async () => {
    const withdrawImpl = vi.fn(async () => ({ ok: false as const, problem: "network" as const }));
    renderWithIntl(
      <WithdrawTag proposalId={PROPOSAL} tagId="t1" orgName="Telmark" returnFocusTo="x" withdrawImpl={withdrawImpl} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    });
    expect(screen.getByRole("alert").textContent).toBe("We could not reach the server. Check your connection, then try again.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("stays open while the withdrawal is under way: Escape and Keep it wait", async () => {
    let settle: (value: { ok: false; problem: "failed" }) => void = () => {};
    const withdrawImpl = vi.fn(() => new Promise<{ ok: false; problem: "failed" }>((resolve) => (settle = resolve)));
    renderWithIntl(
      <WithdrawTag proposalId={PROPOSAL} tagId="t1" orgName="Telmark" returnFocusTo="x" withdrawImpl={withdrawImpl} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the pitch to Telmark" }));
    const dialog = screen.getByRole("dialog");
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    });
    const escape = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(escape);
    expect(escape.defaultPrevented).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(dialog.hasAttribute("open")).toBe(true);
    await act(async () => settle({ ok: false, problem: "failed" }));
    const later = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(later);
    expect(later.defaultPrevented).toBe(false);
  });
});

describe("the idea's pitches", () => {
  const TAGS: MyTags = {
    cap: { used: 2, limit: 5, plan: "dev_free" },
    items: [
      tag(),
      tag({
        id: "0199a000-0000-7000-8000-0000000000f2",
        org: { id: TELMARK, name: "Telmark", slug: "telmark", badge: { level: "e0", text: "Listed" } },
        status: "held_unclaimed",
      }),
      tag({ id: "0199a000-0000-7000-8000-0000000000f3", status: "withdrawn", open: false, org: null }),
      tag({ id: "0199a000-0000-7000-8000-0000000000f4", status: "expired", open: false }),
    ],
  };

  async function renderPitches(props: Partial<Parameters<typeof Pitches>[0]> = {}) {
    return renderWithIntl(await Pitches({ ideaId: PROPOSAL, status: "published", tags: TAGS, ...props }));
  }

  it("lists each company with its state as icon and words, one chip each, and Withdraw only for a saved one", async () => {
    await renderPitches();
    expect(screen.getByText("3 of 5 pitches left for this idea on your plan.")).toBeTruthy();
    const rows = within(screen.getByRole("list", { name: "Companies you pitched this idea to" })).getAllByRole("listitem");
    expect(rows.map((row) => row.querySelector("[data-status]")?.textContent)).toEqual([
      "Sent",
      "Saved until they verify",
      "Withdrawn",
      "Closed",
    ]);
    for (const row of rows) {
      expect(row.querySelectorAll("[data-status], [data-chip]").length).toBeLessThanOrEqual(2);
      expect(row.querySelector("[data-status] svg")).not.toBeNull();
    }
    expect(within(rows[0]).getByRole("link", { name: "Safcell" }).getAttribute("href")).toBe(`/dev/companies/${SAFCELL}`);
    expect(within(rows[1]).getByText(/Telmark isn't on the platform yet/)).toBeTruthy();
    expect(within(rows[1]).getByRole("button", { name: "Withdraw the pitch to Telmark" })).toBeTruthy();
    expect(within(rows[2]).getByText("A company no longer listed")).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("links a pitch that opened an engagement to its tracker (REQ-ENG-03)", async () => {
    const engagement = "0199b000-0000-7000-8000-00000000e001";
    await renderPitches({ tags: { ...TAGS, items: [tag({ engagement_id: engagement })] } });
    expect(screen.getByRole("link", { name: "Open the tracker" }).getAttribute("href")).toBe(
      `/dev/engagements/${engagement}`,
    );
  });

  it("offers the first pitch as its empty state: one sentence and one action", async () => {
    const { container } = await renderPitches({ tags: { ...TAGS, items: [] } });
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.querySelector("p")?.textContent).toBe("You have not pitched this idea yet.");
    expect(within(empty as HTMLElement).getByRole("link").getAttribute("href")).toBe(`/dev/ideas/${PROPOSAL}/pitch`);
  });

  it("says when the plan's pitches are used up, and why an idea cannot be pitched", async () => {
    await renderPitches({ tags: { cap: { used: 5, limit: 5, plan: "dev_free" }, items: [] } });
    expect(screen.getByText("You have used all 5 pitches for this idea on your plan.")).toBeTruthy();
    expect(document.querySelector("[data-empty-state]")).toBeNull();
    cleanup();
    await renderPitches({ status: "held", tags: { ...TAGS, items: [] } });
    expect(screen.getByText("You can pitch this idea once its review is finished.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("says in one sentence when the list could not be read", async () => {
    await renderPitches({ tags: null });
    expect(screen.getByText("Your pitches did not load. Reload the page to try again.")).toBeTruthy();
  });
});

describe("who has seen this", () => {
  const VIEWS: ProposalViews = {
    note: "The API's note, never shown",
    items: [
      {
        view_id: "0199a000-0000-7000-8000-000000000101",
        viewed_at: "2026-09-29T11:06:25Z",
        org: { id: SAFCELL, name: "Safcell" },
        viewer_name: "Rita Wanjiru",
        version_no: 2,
        render_kind: "html",
        duration: null,
        nda_version: "1.0",
      },
      {
        view_id: "0199a000-0000-7000-8000-000000000102",
        viewed_at: "2026-09-28T07:00:00Z",
        org: { id: TELMARK, name: null },
        viewer_name: "Otieno",
        version_no: 1,
        render_kind: "html",
        duration: null,
        nda_version: null,
      },
    ],
  };

  it("lists each view with the person, organisation, Nairobi time, version and NDA version", async () => {
    renderWithIntl(await WhoHasSeen({ views: VIEWS }));
    expect(
      screen.getByText(
        "People at verified companies open the full details only after accepting our NDA, and every view is logged and watermarked to the viewer.",
      ),
    ).toBeTruthy();
    const rows = within(screen.getByRole("list", { name: "Views of the full details, newest first" })).getAllByRole("listitem");
    expect(rows[0].textContent).toContain("Rita Wanjiru, Safcell");
    expect(rows[0].textContent).toContain("29 Sep 2026, 14:06 Nairobi time");
    expect(rows[0].textContent).toContain("Version 2");
    expect(rows[0].textContent).toContain("NDA 1.0");
    expect(rows[1].textContent).toContain("Otieno, a company no longer listed");
    expect(rows[1].textContent).not.toContain("NDA");
    expect(screen.queryByText("The API's note, never shown")).toBeNull();
  });

  it("has an empty state of one sentence and one action", async () => {
    const { container } = renderWithIntl(await WhoHasSeen({ views: { note: "", items: [] } }));
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.querySelector("p")?.textContent).toBe("Nobody has opened the full details yet.");
    expect(within(empty as HTMLElement).getAllByRole("link")).toHaveLength(1);
  });

  it("says in one sentence when the log could not be read", async () => {
    renderWithIntl(await WhoHasSeen({ views: null }));
    expect(screen.getByText("This list did not load. Reload the page to try again.")).toBeTruthy();
  });
});
