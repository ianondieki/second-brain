import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { detail, history } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { Actions, type ActionsProps } from "./Actions";
import type { CommandOutcome } from "./calls";
import { Procurement } from "./Deal";
import { HistoryList } from "./HistoryList";
import { refusalOf } from "./calls";
import { actionItems, isPublicEntity, stepperSteps, subStages, type CommandRequest, type Detail, type StageStep } from "./model";
import { plainJustification } from "./procurement";
import { Stepper, SubStageList } from "./Stepper";
import { WhoseTurn } from "./WhoseTurn";

// P28 tracks A and B (REQ-ENG-06, AC-TRACK-5; REQ-NOT-05): a public entity's tracker has stage 3b, where its owner or
// admin chooses the procurement route in a sheet; both parties then read the route; the organisation's tracker says
// when a stage was escalated to its admins, the developer's never does.

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

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

const step = (state: StageStep["state"], label: string, group: StageStep["group"]): StageStep => ({ state, label, group });

/** The API's `steps` for a tagged proposal: with 3b for a public entity, without it for a private organisation. */
function stepsOf(publicEntity: boolean): StageStep[] {
  return [
    step("SUBMITTED", "Proposal submitted", "review"),
    step("UNDER_REVIEW", "Under review", "review"),
    ...(publicEntity ? [step("PROCUREMENT_ROUTE", "Procurement route", "contact_nda")] : []),
    step("INTEREST_CONFIRMED", "Approved to proceed (non-binding)", "contact_nda"),
    step("CONTACT_MADE", "First contact", "contact_nda"),
    step("NDA_PENDING", "Mutual NDA: awaiting both signatures", "contact_nda"),
    step("NDA_SIGNED", "Mutual NDA signed", "contact_nda"),
    step("NEGOTIATION", "Terms and agreement drafting", "agreement"),
  ];
}

/** The organisation's tracker in 3b, for a member with `roles` (an owner or admin gets choose_route). */
function inRoute(roles: Array<"owner" | "admin" | "signatory" | "reviewer">, overrides: Partial<Detail> = {}): Detail {
  const decides = roles.includes("owner") || roles.includes("admin");
  return detail({
    my_party: "org",
    my_roles: roles,
    state: "PROCUREMENT_ROUTE",
    stage_label: "Procurement route",
    stage_group: "contact_nda",
    steps: stepsOf(true),
    whose_turn: ["org"],
    awaiting: [{ command: "choose_route", party: "org" }],
    actions: decides ? ["choose_route", "pause"] : ["pause"],
    today: "2026-10-13",
    lock_version: 7,
    ...overrides,
  } as Partial<Detail>);
}

describe("the stepper's stages from the API's steps (AC-TRACK-5)", () => {
  it("lists 3b in Contact and NDA for a public entity, and never for a private organisation", () => {
    const publicStages = subStages(stepsOf(true), "PROCUREMENT_ROUTE");
    expect(publicStages.map((s) => [s.state, s.mark])).toEqual([
      ["PROCUREMENT_ROUTE", "current"],
      ["INTEREST_CONFIRMED", "pending"],
      ["CONTACT_MADE", "pending"],
      ["NDA_PENDING", "pending"],
      ["NDA_SIGNED", "pending"],
    ]);
    const privateStages = subStages(stepsOf(false), "CONTACT_MADE");
    expect(privateStages.map((s) => s.state)).not.toContain("PROCUREMENT_ROUTE");
    expect(privateStages.map((s) => [s.state, s.mark])).toEqual([
      ["INTEREST_CONFIRMED", "completed"],
      ["CONTACT_MADE", "current"],
      ["NDA_PENDING", "pending"],
      ["NDA_SIGNED", "pending"],
    ]);
    expect(isPublicEntity({ steps: stepsOf(true) })).toBe(true);
    expect(isPublicEntity({ steps: stepsOf(false) })).toBe(false);
    expect(isPublicEntity({ steps: undefined })).toBe(false);
  });

  it("gives the stage it stopped at the group's own chip while paused, questioned or overdue, never Current", () => {
    const steps = stepsOf(true);
    const at = (here: Parameters<typeof subStages>[2]) =>
      subStages(steps, "UNDER_REVIEW", here).find((s) => s.state === "UNDER_REVIEW");
    // ON_HOLD from UNDER_REVIEW: the stepper's own chip for the group, then the sub-stage's.
    const paused = stepperSteps({ state: "ON_HOLD", stage_group: null, due: null, paused_from: "UNDER_REVIEW" });
    expect(at(paused.find((s) => s.group === "review"))).toMatchObject({ mark: "onHold" });
    const asked = stepperSteps({ state: "INFO_REQUESTED", stage_group: null, due: null, paused_from: "UNDER_REVIEW" });
    expect(at(asked.find((s) => s.group === "review"))).toMatchObject({ mark: "onHold", word: "awaitingAnswer" });
    expect(at({ chip: "overdue" })).toMatchObject({ mark: "overdue" });
    expect(subStages(steps, "UNDER_REVIEW", { chip: "overdue" }).map((s) => s.mark)).toEqual(["completed", "overdue"]);
  });

  it("lists nothing once the engagement has ended or closed", () => {
    expect(subStages(stepsOf(true), "UNDER_REVIEW", { chip: "ended" })).toEqual([]);
    expect(subStages(stepsOf(true), "NDA_SIGNED", { chip: "completed" })).toEqual([]);
  });

  it("says a paused stage's own word to screen readers, and names stages from the locales", () => {
    const paused = subStages(stepsOf(true), "UNDER_REVIEW", { chip: "onHold", word: "awaitingAnswer" });
    // The API's label is ignored where the locales name the stage.
    renderWithIntl(<SubStageList stages={paused.map((s) => ({ ...s, label: "x" }))} group="review" />);
    const items = within(screen.getByRole("list", { name: "Within Review" })).getAllByRole("listitem");
    expect(items[1].getAttribute("data-state")).toBe("onHold");
    expect(items[1].querySelector("[data-substage-word]")?.textContent).toBe("Waiting for an answer");
    expect(items[1].textContent).toContain("Under review: Waiting for an answer");
    expect(items[1].textContent).not.toContain("Current");
    expect(items[0].textContent).toContain("Proposal submitted: Completed");
  });

  it("keeps the API's label for a stage the locales do not name", () => {
    renderWithIntl(
      <SubStageList
        stages={[
          { state: "SUBMITTED", label: "Proposal submitted", mark: "completed" },
          { state: "NEW_STAGE" as StageStep["state"], label: "A later stage", mark: "current" },
        ]}
        group="review"
      />,
    );
    expect(screen.getByText("A later stage: Current")).toBeTruthy();
  });

  it("lists nothing for a stage outside the steps, or a group of one stage", () => {
    expect(subStages(stepsOf(true), null)).toEqual([]);
    expect(subStages([step("NEGOTIATION", "Terms and agreement drafting", "agreement")], "NEGOTIATION")).toEqual([]);
  });

  it("draws the current group's stages with their status for screen readers", () => {
    // Its name never contains the stepper's own ("Stages"), so a lookup of the stepper by name finds one list.
    renderWithIntl(<SubStageList stages={subStages(stepsOf(true), "PROCUREMENT_ROUTE")} group="contact_nda" />);
    const list = screen.getByRole("list", { name: "Within Contact and NDA" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0].getAttribute("data-substage")).toBe("PROCUREMENT_ROUTE");
    expect(items[0].textContent).toContain("Procurement route: Current");
    expect(items[1].textContent).toContain("Approved to proceed (non-binding): Pending");
    // The current stage's word shows too (mark, words and colour); done and pending ones keep the mark alone.
    expect(items[0].querySelector("[data-substage-word]")?.textContent).toBe("Current");
    expect(items[0].querySelector("[data-substage-word]")?.className).toContain("text-accent");
    expect(items[1].querySelector("[data-substage-word]")).toBeNull();
  });
});

describe("the stepper's sub-stage list, by width", () => {
  const stages = subStages(stepsOf(true), "PROCUREMENT_ROUTE");
  const steps = stepperSteps({ state: "PROCUREMENT_ROUTE", stage_group: "contact_nda", due: null });

  it("draws a column under the current step for phones and a row under the spine from 1024 px", () => {
    const { container } = renderWithIntl(
      <Stepper steps={steps} stages={(layout) => <SubStageList stages={stages} group="contact_nda" layout={layout} />} />,
    );
    const column = container.querySelector<HTMLElement>("[data-substages='column']")!;
    // The column sits in the current step and hides from 1024 px.
    expect(column.closest("li[aria-current='step']")?.getAttribute("data-group")).toBe("contact_nda");
    expect(column.parentElement?.className).toContain("lg:hidden");
    // The row is outside the list of groups, hidden on phones, and starts at the current group's column.
    const row = container.querySelector<HTMLElement>("[data-substages-row]")!;
    expect(row.closest("[data-stepper]")).toBeNull();
    expect(row.className).toContain("hidden");
    expect(row.className).toContain("lg:grid");
    expect(row.firstElementChild?.getAttribute("style")).toContain("grid-column: 2 / -1");
    const list = row.querySelector<HTMLElement>("[data-substages='row']")!;
    expect(list.className).toContain("flex-wrap");
    expect([...list.querySelectorAll("li")].every((li) => li.className.includes("whitespace-nowrap"))).toBe(true);
    // The stepper's own five groups, the nested list apart.
    expect(container.querySelectorAll("[data-stepper] > li")).toHaveLength(5);
  });

  it("draws neither without stages", () => {
    const { container } = renderWithIntl(<Stepper steps={steps} />);
    expect(container.querySelector("[data-substages]")).toBeNull();
    expect(container.querySelector("[data-substages-row]")).toBeNull();
  });
});

type Run = (request: CommandRequest) => Promise<CommandOutcome>;

function renderActions(engagement: Detail, props: Partial<Omit<ActionsProps, "runImpl">> & { runImpl?: Run } = {}) {
  const runImpl = vi.fn<Run>(props.runImpl ?? (async () => ({ ok: true })));
  const view = renderWithIntl(
    <Actions
      engagementId={engagement.id}
      lockVersion={engagement.lock_version}
      items={actionItems(engagement)}
      counterpart={engagement.developer_name}
      enrolled
      today={engagement.today ?? null}
      orgId={engagement.org_id}
      publicEntity={isPublicEntity(engagement)}
      {...props}
      runImpl={runImpl}
    />,
  );
  return { ...view, runImpl };
}

const sheet = async () => (await screen.findByRole("dialog")) as HTMLDialogElement;

async function openSheet(engagement = inRoute(["owner", "admin"]), props: Parameters<typeof renderActions>[1] = {}) {
  const view = renderActions(engagement, props);
  const button = screen.getByRole("button", { name: "Choose the procurement route" });
  expect(button.hasAttribute("data-primary")).toBe(true);
  fireEvent.click(button);
  return { ...view, dialog: await sheet() };
}

describe("the procurement route's sheet (REQ-ENG-06)", () => {
  it("offers the five routes, each with one sentence, and today as the contact-by date", async () => {
    const { dialog } = await openSheet();
    expect(dialog.hasAttribute("data-sheet")).toBe(true); // the bottom sheet on phones (D-52)
    expect(within(dialog).getByRole("heading", { name: "Choose the procurement route" })).toBeTruthy();
    const group = within(dialog).getByRole("group", { name: "How will you buy it?" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual([
      "rfq_tender",
      "direct",
      "ppp_pip",
      "innovation_challenge",
      "pilot_mou",
    ]);
    await waitFor(() => expect(document.activeElement).toBe(radios[0]));
    for (const radio of radios) expect(radio.getAttribute("aria-describedby")).toBeTruthy();
    expect(within(dialog).getByLabelText(/Direct procurement/).closest("label")?.textContent).toContain(
      "without a competition",
    );
    const date = within(dialog).getByLabelText("Contact by") as HTMLInputElement;
    expect(date.value).toBe("2026-10-13");
    expect(date.min).toBe("2026-10-13");
    expect(within(dialog).getByText("0 of 1,000 characters")).toBeTruthy();
    // The confirm button is styled, not marked, as primary: the page keeps one data-primary.
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    // The statute stays out of the sentences: plain words only.
    expect(dialog.textContent).not.toMatch(/PPADA|Act 20\d\d/);
  });

  it("asks for a route before anything is sent", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" }));
    expect(within(dialog).getByText("Choose a procurement route.")).toBeTruthy();
    expect(runImpl).not.toHaveBeenCalled();
  });

  it("requires 20 characters of justification for direct procurement, and says so on the field", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Direct procurement/ }));
    const field = within(dialog).getByLabelText("Justification");
    expect(field.getAttribute("aria-required")).toBe("true");
    expect(field.getAttribute("maxlength")).toBe("1000");
    expect(dialog.textContent).toContain("Direct procurement needs a written reason of 20 to 1,000 characters.");
    fireEvent.change(field, { target: { value: "   Only one vendor.   " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" }));
    expect(runImpl).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByText("Direct procurement needs a written justification of at least 20 characters.")).toBeTruthy();
    expect(document.activeElement).toBe(field);
  });

  it("sends the route, the trimmed justification and the date under the organisation's path", async () => {
    const engagement = inRoute(["owner", "admin"]);
    const { dialog, runImpl } = await openSheet(engagement);
    fireEvent.click(within(dialog).getByRole("radio", { name: /Direct procurement/ }));
    const reason = "  The county already runs this developer's USSD gateway.  ";
    fireEvent.change(within(dialog).getByLabelText("Justification"), { target: { value: reason } });
    expect(within(dialog).getByText(`${reason.length} of 1,000 characters`)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Contact by"), { target: { value: "2026-10-16" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect(runImpl).toHaveBeenCalledWith({
      path: "/api/orgs/{org_id}/engagements/{engagement_id}/procurement-route",
      params: { org_id: engagement.org_id, engagement_id: engagement.id },
      body: {
        route: "direct",
        justification: "The county already runs this developer's USSD gateway.",
        contact_by: "2026-10-16",
        lock_version: 7,
      },
    });
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Done. The tracker is up to date.");
  });

  it("counts characters as the API does (code points), so 12 emoji are 12, not 24", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Direct procurement/ }));
    const field = within(dialog).getByLabelText("Justification");
    fireEvent.change(field, { target: { value: "🐄".repeat(12) } });
    expect(within(dialog).getByText("12 of 1,000 characters")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" }));
    expect(runImpl).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(field, { target: { value: "🐄".repeat(20) } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect(runImpl).toHaveBeenCalledTimes(1);
  });

  it("drops the control characters the API refuses, keeping line feeds and tabs (REQ-ENG-06)", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Direct procurement/ }));
    fireEvent.change(within(dialog).getByLabelText("Justification"), {
      target: { value: "\u0007 Only this developer\u0000 runs\tthe gateway;\nno other\u001b supplier\u007f does. \r" },
    });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect((runImpl.mock.calls[0][0].body as { justification?: string }).justification).toBe("Only this developer runs\tthe gateway;\nno other supplier does.");
    expect(plainJustification("  \u0001\u0002  ")).toBe("");
  });

  it("takes no justification for another route (null), and labels it optional", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Request for quotation or tender/ }));
    expect(within(dialog).getByLabelText("Justification (optional)").getAttribute("aria-required")).toBeNull();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect(runImpl.mock.calls[0][0].body).toEqual({
      route: "rfq_tender",
      justification: null,
      contact_by: "2026-10-13",
      lock_version: 7,
    });
  });

  // justification_required and invalid_justification fall back to a plain 422 ("invalid", calls.ts), as does the
  // schema's refusal of the text's characters: the sheet says it on the justification.
  it.each([
    ["invalid", "Justification", "That justification was not accepted. Write it in plain words, in no more than 1,000 characters."],
    ["containsContact", "Justification", "Contact details stay out of the tracker until first contact is made"],
    ["invalidContactBy", "Contact by", "Choose a contact-by date from today, no more than five business days ahead."],
  ] as const)("keeps the sheet open on a 422 %s, the reason on its field, which takes the focus", async (refusal, label, words) => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal, status: 422 }));
    const { dialog } = await openSheet(inRoute(["admin"]), { runImpl });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Direct procurement/ }));
    fireEvent.change(within(dialog).getByLabelText("Justification"), {
      target: { value: "Reach me on 0712 345 678 for the gateway details." },
    });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect(screen.getByRole("dialog")).toBe(dialog);
    const field = within(dialog).getByLabelText(label);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(dialog.textContent).toContain(words);
    await waitFor(() => expect(document.activeElement).toBe(field));
    // The text stays as typed, for correcting.
    expect((within(dialog).getByLabelText("Justification") as HTMLTextAreaElement).value).toContain("0712 345 678");
  });

  it("closes and refreshes when the engagement moved on (409), saying so", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "conflict", status: 409 }));
    const { dialog } = await openSheet(inRoute(["owner"]), { runImpl });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Pilot under a memorandum/ }));
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Confirm the route" })));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByText(/That step is no longer possible/)).toBeTruthy();
  });

  it("closes on Cancel without sending, and gives focus back to its button", async () => {
    const { dialog, runImpl } = await openSheet();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(runImpl).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Choose the procurement route" })),
    );
  });
});

describe("the route's refusals in the first load (calls.ts)", () => {
  it("leave the justification's codes to a plain 422, which the sheet says on its field", () => {
    for (const code of ["justification_required", "invalid_justification"]) {
      expect(refusalOf(422, { detail: { code, message: "x" } })).toBe("invalid");
    }
    expect(refusalOf(422, { detail: { code: "invalid_contact_by", message: "x" } })).toBe("invalidContactBy");
  });
});

describe("who chooses, in the whose-turn banner", () => {
  it("names the step for an owner or admin, who has the button", () => {
    renderWithIntl(<WhoseTurn detail={inRoute(["owner", "admin"])} />);
    expect(screen.getByText("Your next step: Choose the procurement route")).toBeTruthy();
    expect(screen.getByText("Your turn")).toBeTruthy();
    expect(document.querySelector("[data-waiting-admin]")).toBeNull();
  });

  it("tells a signatory or reviewer that an admin chooses it", () => {
    for (const roles of [["signatory"], ["reviewer"]] as const) {
      renderWithIntl(<WhoseTurn detail={inRoute([...roles])} />);
      expect(screen.getByText("Waiting for an admin to choose the procurement route.")).toBeTruthy();
      expect(screen.queryByText("Your next step: Choose the procurement route")).toBeNull();
      // The organisation's turn, not this member's: no "Your turn" badge, the admins named as who is awaited.
      expect(screen.getByRole("heading", { name: "Awaiting: your admins" })).toBeTruthy();
      expect(screen.queryByText("Your turn")).toBeNull();
      cleanup();
    }
  });

  it("tells the developer what the organisation does next", () => {
    renderWithIntl(
      <WhoseTurn
        detail={detail({
          state: "PROCUREMENT_ROUTE",
          steps: stepsOf(true),
          whose_turn: ["org"],
          awaiting: [{ command: "choose_route", party: "org" }],
          actions: ["withdraw", "pause"],
        } as Partial<Detail>)}
      />,
    );
    expect(screen.getByText("Next step for Telco A (fixture): Choose the procurement route")).toBeTruthy();
  });
});

describe("an escalation on the organisation's tracker (REQ-NOT-05)", () => {
  const escalated = "2026-10-13T06:15:00Z";

  it("says once, quietly, when the stage was escalated to the admins", () => {
    renderWithIntl(<WhoseTurn detail={inRoute(["signatory"], { escalated_at: escalated } as Partial<Detail>)} />);
    const line = document.querySelector("[data-escalated]")!;
    expect(line.textContent).toBe("Escalated to the admins on 13 Oct 2026.");
    expect(line.className).toContain("text-ink-soft");
    expect(line.className).not.toMatch(/error|warm/);
    expect(document.querySelectorAll("[data-escalated]")).toHaveLength(1);
  });

  it("says nothing without an escalation", () => {
    renderWithIntl(<WhoseTurn detail={inRoute(["admin"], { escalated_at: null } as Partial<Detail>)} />);
    expect(document.querySelector("[data-escalated]")).toBeNull();
  });

  it("never shows on the developer's tracker, even if a field came through", () => {
    renderWithIntl(
      <WhoseTurn detail={detail({ state: "INTEREST_CONFIRMED", escalated_at: escalated } as Partial<Detail>)} />,
    );
    expect(document.querySelector("[data-escalated]")).toBeNull();
    expect(document.body.textContent).not.toContain("Escalated");
  });
});

describe("the route, once chosen, for both parties", () => {
  const procurement = {
    route: "direct" as const,
    justification: "The county already runs this developer's USSD gateway.\nA tender would duplicate it.",
    decided_at: "2026-10-13T08:05:00Z",
    decided_by_name: "Halima Yusuf",
  };

  it("shows the route, the justification as written, who chose it and when", () => {
    for (const party of ["developer", "org"] as const) {
      renderWithIntl(<Procurement detail={{ procurement }} />);
      const section = screen.getByRole("region", { name: "Procurement route" });
      expect(section.querySelector("[data-route]")?.textContent).toBe("Direct procurement");
      expect(section.querySelector("[data-justification]")?.textContent).toBe(procurement.justification);
      expect(section.textContent).toContain("Halima Yusuf");
      expect(section.textContent).toContain("13 Oct 2026, 11:05 EAT");
      cleanup();
      void party;
    }
  });

  it("leaves the justification out when none was given, and draws nothing before the choice", () => {
    renderWithIntl(<Procurement detail={{ procurement: { ...procurement, route: "pilot_mou", justification: null } }} />);
    expect(screen.queryByText("Justification")).toBeNull();
    expect(screen.getByText("Pilot under a memorandum of understanding")).toBeTruthy();
    cleanup();
    const { container } = renderWithIntl(<Procurement detail={{ procurement: null }} />);
    expect(container.textContent).toBe("");
  });

  it("names the decision and its route in History", () => {
    const base = history();
    const chosen = {
      ...base.events[1],
      id: "0199b000-0000-7000-8000-0000000000e3",
      seq: 3,
      created_at: "2026-10-13T08:05:00Z",
      actor_name: "Halima Yusuf",
      actor_role: "admin" as const,
      command: "choose_route",
      from_state: "PROCUREMENT_ROUTE" as const,
      to_state: "INTEREST_CONFIRMED" as const,
      payload: { procurement_route: "rfq_tender", contact_by: "2026-10-16" },
    };
    renderWithIntl(<HistoryList history={{ ...base, events: [...base.events, chosen] }} />);
    const entry = document.querySelector("[data-event='choose_route']")!;
    expect(entry.textContent).toContain("Procurement route chosen");
    expect(entry.textContent).toContain("Halima Yusuf, Admin");
    expect(entry.querySelector("[data-event-route]")?.textContent).toBe("Route: Request for quotation or tender");
  });

  it("words a public entity's approval as leading to the route, not to stage 3; a private one's as before", () => {
    const base = history();
    const approval = (to_state: "PROCUREMENT_ROUTE" | "INTEREST_CONFIRMED") => ({
      ...base.events[1],
      id: `0199b000-0000-7000-8000-0000000000${to_state === "PROCUREMENT_ROUTE" ? "e4" : "e5"}`,
      seq: 3,
      actor_name: "Otieno Mwita",
      command: "approve",
      from_state: "UNDER_REVIEW" as const,
      to_state,
    });
    renderWithIntl(<HistoryList history={{ ...base, events: [...base.events, approval("PROCUREMENT_ROUTE")] }} />);
    const entry = document.querySelector("[data-event='approve']")!;
    expect(entry.querySelector("h3")?.textContent).toBe("Approved; the procurement route comes next");
    expect(entry.textContent).not.toContain("Approved to proceed");
    cleanup();
    renderWithIntl(<HistoryList history={{ ...base, events: [...base.events, approval("INTEREST_CONFIRMED")] }} />);
    expect(document.querySelector("[data-event='approve'] h3")?.textContent).toBe("Approved to proceed (non-binding)");
  });

  it("ignores a route it does not know in an event's payload", () => {
    const base = history();
    const odd = { ...base.events[1], id: "x", seq: 3, command: "choose_route", payload: { procurement_route: "<b>x</b>" } };
    renderWithIntl(<HistoryList history={{ ...base, events: [...base.events, odd] }} />);
    expect(document.querySelector("[data-event-route]")).toBeNull();
  });
});

describe("a public entity's approve form", () => {
  const reviewing = (publicEntity: boolean) =>
    detail({
      my_party: "org",
      my_roles: ["signatory"],
      state: "UNDER_REVIEW",
      steps: stepsOf(publicEntity),
      actions: ["approve", "decline"],
      awaiting: [{ command: "approve", party: "org" }],
      lock_version: 5,
    } as Partial<Detail>);
  const members = [{ user_id: "u-halima", display_name: "Halima Yusuf" }];

  it("does not ask for the contact-by date: it is set with the route", async () => {
    const engagement = reviewing(true);
    const { runImpl } = renderActions(engagement, { members, myUserId: "u-halima" });
    fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" }));
    await waitFor(() => expect(screen.getByLabelText("Contact person")).toBeTruthy());
    expect(screen.queryByLabelText("Contact by")).toBeNull();
    expect(screen.getByText(/An owner or admin then chooses the procurement route and sets the contact-by date/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/approve",
      params: { engagement_id: engagement.id },
      body: { contact_user_id: "u-halima", contact_channel: "email", lock_version: 5 },
    });
  });

  it("still asks a private organisation for the date", async () => {
    renderActions(reviewing(false), { members, myUserId: "u-halima" });
    fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" }));
    await waitFor(() => expect(screen.getByLabelText("Contact by")).toBeTruthy());
    expect(screen.queryByText(/chooses the procurement route/)).toBeNull();
  });
});
