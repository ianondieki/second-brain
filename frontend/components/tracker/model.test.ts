import { describe, expect, it } from "vitest";

import { detail, history, inImplementation, summary } from "@/test/engagement";

import {
  actionItems,
  awaitsMe,
  commandRequest,
  documentKinds,
  eatParts,
  endorsementRows,
  formatDate,
  kesAmount,
  milestoneTargets,
  notesByEvent,
  offersContactReveal,
  sideBanner,
  stageChip,
  stageLeft,
  stepperSteps,
  toMinor,
  turnOf,
  withQuery,
  type ChipKind,
} from "./model";
import { addDays } from "./sheet";

// REQ-ENG-03 (AC-TRACK-3/4 prototype part): the tracker's view model. The stepper's groups come from `stage_group`,
// whose turn from `whose_turn`, the buttons only from `actions`; nothing here decides who may act.

const chips = (steps: Array<{ chip: ChipKind }>) => steps.map((s) => s.chip);

describe("the 5-group stepper", () => {
  it.each([
    ["review", ["current", "pending", "pending", "pending", "pending"]],
    ["contact_nda", ["completed", "current", "pending", "pending", "pending"]],
    ["agreement", ["completed", "completed", "current", "pending", "pending"]],
    ["implementation", ["completed", "completed", "completed", "current", "pending"]],
    ["close", ["completed", "completed", "completed", "completed", "current"]],
  ])("puts the current group at %s from stage_group", (group, expected) => {
    const steps = stepperSteps({ state: "UNDER_REVIEW", stage_group: group, due: null });
    expect(steps.map((s) => s.group)).toEqual(["review", "contact_nda", "agreement", "implementation", "close"]);
    expect(chips(steps)).toEqual(expected);
  });

  it("marks the current group overdue past its deadline", () => {
    const steps = stepperSteps({
      state: "NDA_PENDING",
      stage_group: "contact_nda",
      due: { due_on: "2026-09-25", business_days_left: -2, overdue: true },
    });
    expect(chips(steps)).toEqual(["completed", "overdue", "pending", "pending", "pending"]);
  });

  it("completes every group once the engagement is closed", () => {
    expect(chips(stepperSteps({ state: "CLOSED", stage_group: "close", due: null }))).toEqual(Array(5).fill("completed"));
  });

  it("ends in the group of the stage it left when declined or withdrawn (the API sends no group then)", () => {
    const steps = stepperSteps({ state: "DECLINED", stage_group: null, due: null, left: "UNDER_REVIEW" });
    expect(chips(steps)).toEqual(["ended", "pending", "pending", "pending", "pending"]);
    const late = stepperSteps({ state: "WITHDRAWN", stage_group: null, due: null, left: "NEGOTIATION" });
    expect(chips(late)).toEqual(["completed", "completed", "ended", "pending", "pending"]);
  });

  it("shows a paused engagement on hold", () => {
    const steps = stepperSteps({ state: "ON_HOLD", stage_group: null, due: null, left: "IN_IMPLEMENTATION" });
    expect(chips(steps)).toEqual(["completed", "completed", "completed", "onHold", "pending"]);
  });

  it("reads the stage an engagement left from the event that entered its state", () => {
    const events = history().events;
    const declined = [
      ...events,
      { ...events[1], id: "e3", seq: 3, command: "decline", from_state: "UNDER_REVIEW" as const, to_state: "DECLINED" as const },
    ];
    expect(stageLeft("DECLINED", declined)).toBe("UNDER_REVIEW");
    expect(stageLeft("DECLINED", null)).toBeNull();
  });
});

describe("list chips and whose turn", () => {
  it.each([
    [summary(), "current"],
    [summary({ due: { due_on: "2026-09-20", business_days_left: -3, overdue: true } }), "overdue"],
    [summary({ state: "CLOSED" }), "completed"],
    [summary({ state: "WITHDRAWN" }), "ended"],
    [summary({ state: "ON_HOLD" }), "onHold"],
  ] as const)("chips %# as %s", (item, chip) => {
    expect(stageChip(item)).toBe(chip);
  });

  it("says whose turn it is from the caller's side", () => {
    expect(turnOf(summary({ whose_turn: ["org"] }), "developer")).toEqual({ kind: "other", party: "org" });
    expect(turnOf(summary({ whose_turn: ["org"] }), "org")).toEqual({ kind: "you" });
    expect(turnOf(summary({ whose_turn: ["developer", "org"] }), "org")).toEqual({ kind: "both" });
    expect(turnOf(summary({ whose_turn: [] }), "org")).toEqual({ kind: "none" });
    expect(turnOf(summary({ state: "DECLINED", whose_turn: [] }), "developer")).toEqual({ kind: "ended" });
    expect(awaitsMe(summary({ whose_turn: ["developer"] }), "developer")).toBe(true);
    expect(awaitsMe(summary({ state: "CLOSED", whose_turn: ["developer"] }), "developer")).toBe(false);
  });

  it("gives each party's endorsement of the current stage, leaving milestone endorsements out", () => {
    const rows = endorsementRows(
      detail({
        state: "CONTACT_MADE",
        endorsements: [
          {
            id: "x1",
            stage: "CONTACT_MADE",
            stage_round: 1,
            milestone_id: null,
            party: "org",
            user_id: "u1",
            name: "Rita Wanjiru",
            role: "signatory",
            method: "totp",
            endorsed_at: "2026-09-24T07:00:00Z",
          },
          {
            id: "x2",
            stage: "CONTACT_MADE",
            stage_round: 1,
            milestone_id: "m1",
            party: "developer",
            user_id: "u2",
            name: "Achieng Otieno",
            role: "developer",
            method: "totp",
            endorsed_at: "2026-09-24T08:00:00Z",
          },
        ],
      }),
    );
    expect(rows.org?.name).toBe("Rita Wanjiru");
    expect(rows.developer).toBeNull();
  });
});

describe("actions become buttons, and buttons become requests", () => {
  it("makes the awaited step primary and puts ending steps last, from the API's actions only", () => {
    const items = actionItems(
      detail({
        my_party: "org",
        actions: ["decline", "approve"],
        awaiting: [{ command: "approve", party: "org" }],
      }),
    );
    expect(items.map((i) => [i.command, i.primary])).toEqual([
      ["approve", true],
      ["decline", false],
    ]);
  });

  it("never offers a step the API did not list, even when it is awaited", () => {
    const items = actionItems(detail({ my_party: "org", actions: [], awaiting: [{ command: "start_review", party: "org" }] }));
    expect(items).toEqual([]);
  });

  it("never makes an ending step primary", () => {
    const items = actionItems(detail({ actions: ["withdraw"], awaiting: [{ command: "withdraw", party: "developer" }] }));
    expect(items).toEqual([{ command: "withdraw", primary: false }]);
  });

  it("gives a milestone command one button per milestone that can take it", () => {
    const engagement = inImplementation({ my_party: "org", actions: ["accept_milestone", "request_changes"] });
    expect(milestoneTargets("accept_milestone", engagement.agreements).map((m) => m.seq)).toEqual([1]);
    expect(milestoneTargets("start_milestone", engagement.agreements).map((m) => m.seq)).toEqual([2]);
    const items = actionItems(engagement);
    expect(items.map((i) => [i.command, i.milestone?.seq, i.primary])).toEqual([
      ["accept_milestone", 1, true],
      ["request_changes", 1, false],
    ]);
  });

  it("builds each command's request with the lock_version the page read", () => {
    expect(commandRequest("sign_nda", "e1", 7)).toEqual({
      path: "/api/engagements/{engagement_id}/sign-nda",
      params: { engagement_id: "e1" },
      body: { lock_version: 7 },
    });
    expect(commandRequest("submit_milestone", "e1", 7, { milestoneId: "m1" })).toEqual({
      path: "/api/engagements/{engagement_id}/milestones/{milestone_id}/submit",
      params: { engagement_id: "e1", milestone_id: "m1" },
      body: { lock_version: 7 },
    });
    const payment = { amount_kes_minor: 25_000_000, method: "mpesa" as const, reference: "QK12ABC", paid_on: "2026-09-29" };
    expect(commandRequest("record_payment", "e1", 9, { input: payment })).toEqual({
      path: "/api/engagements/{engagement_id}/record-payment",
      params: { engagement_id: "e1" },
      body: { ...payment, lock_version: 9 },
    });
    expect(() => commandRequest("accept_milestone", "e1", 1)).toThrow(TypeError);
  });
});

describe("formatting", () => {
  it("writes moments in Nairobi time with EAT parts", () => {
    expect(eatParts("2026-09-23T11:05:00Z")).toEqual({ date: "23 Sep 2026", time: "14:05" });
    expect(eatParts("2026-09-23T22:30:00Z").date).toBe("24 Sep 2026"); // after midnight in Nairobi
    expect(formatDate("2026-10-02")).toBe("2 Oct 2026");
    expect(formatDate("2026-09-25")).toBe("25 Sep 2026");
    expect(eatParts("2026-09-23T11:05:00Z", "sw").date).toMatch(/^23 Sep 2026$/);
  });

  it("reads and writes shillings", () => {
    expect(kesAmount(125_000_000)).toBe("1,250,000");
    expect(kesAmount(125_050)).toBe("1,250.50");
    expect(toMinor("250,000")).toBe(25_000_000);
    expect(toMinor("1250.5")).toBe(125_050);
    expect(toMinor("0")).toBeNull();
    expect(toMinor("12abc")).toBeNull();
    expect(toMinor("1.234")).toBeNull();
  });
});

describe("the Documents tab", () => {
  it("offers the current stage's document, every signed one and a final agreement, in stage order", () => {
    const signed = {
      id: "s1",
      document_kind: "mutual_nda" as const,
      document_ref: "r1",
      document_sha256: "ab",
      party: "org" as const,
      signer_user_id: "u1",
      signer_name: "Rita Wanjiru",
      step_up_method: "totp" as const,
      signed_at: "2026-09-23T11:05:00Z",
    };
    expect(documentKinds(detail())).toEqual([]);
    expect(documentKinds(detail({ documents: [{ kind: "mutual_nda", ref: "r1", sha256: "ab" }] }))).toEqual(["mutual_nda"]);
    const later = inImplementation({
      signatures: [signed, { ...signed, id: "s2", document_kind: "milestone_confirmation" }],
      documents: [{ kind: "acceptance_certificate", ref: "r2", sha256: "cd" }],
    });
    expect(documentKinds(later)).toEqual(["mutual_nda", "agreement", "acceptance_certificate"]);
  });
});

describe("tracker links", () => {
  it("keep the chosen organisation and add the tab", () => {
    expect(withQuery("/org/engagements/e1")).toBe("/org/engagements/e1");
    expect(withQuery("/org/engagements/e1", "?org=o1")).toBe("/org/engagements/e1?org=o1");
    expect(withQuery("/org/engagements/e1", "?org=o1", { tab: "documents", doc: "agreement" })).toBe(
      "/org/engagements/e1?org=o1&tab=documents&doc=agreement",
    );
    expect(withQuery("/dev/engagements/e1", "", { tab: "history" })).toBe("/dev/engagements/e1?tab=history");
  });
});

describe("the contact reveal", () => {
  const contact = { user_id: "u-rita", name: "Rita Wanjiru", role: "signatory", channel: "email" as const, contact_by: "2026-10-01" };
  const approved = detail({ my_party: "org", state: "INTEREST_CONFIRMED", contact });

  it("is offered to the organisation's named contact once approved", () => {
    expect(offersContactReveal(approved, "u-rita")).toBe(true);
    expect(offersContactReveal({ ...approved, state: "CLOSED" }, "u-rita")).toBe(true);
  });

  it("is not offered to a member who is not the named contact, nor to the developer", () => {
    expect(offersContactReveal(approved, "u-otieno")).toBe(false);
    expect(offersContactReveal({ ...approved, my_party: "developer" }, "u-rita")).toBe(false);
  });

  it("is not offered before the approval or on an ended engagement", () => {
    expect(offersContactReveal({ ...approved, state: "UNDER_REVIEW" }, "u-rita")).toBe(false);
    for (const state of ["DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED"] as const) {
      expect(offersContactReveal({ ...approved, state }, "u-rita"), state).toBe(false);
    }
  });
});

// REQ-ENG-10 part (docs/spec/06 6.9 side branches): a question, a hold and an expiry are said on the stage where they
// occurred, never as extra steps; the stage stays marked through the API's `paused_from`.
describe("side states", () => {
  const asked = { kind: "info_request" as const, body: "Which co-ops ran the pilot?", by: "org" as const, at: "2026-10-01T07:00:00Z", resume_at: null };
  const answered = { kind: "info_answer" as const, body: "Kipkelion and Olenguruone.", by: "developer" as const, at: "2026-10-05T09:00:00Z", resume_at: null };
  const held = { kind: "hold" as const, body: "Budget committee meets on the 20th.", by: "org" as const, at: "2026-10-02T08:00:00Z", resume_at: "2026-10-21" };

  it("keeps the stage it paused from marked, with the On hold chip, for a question and a hold", () => {
    const question = stepperSteps({ state: "INFO_REQUESTED", stage_group: null, due: null, paused_from: "UNDER_REVIEW" });
    expect(chips(question)).toEqual(["onHold", "pending", "pending", "pending", "pending"]);
    const hold = stepperSteps({ state: "ON_HOLD", stage_group: null, due: null, paused_from: "NEGOTIATION" });
    expect(chips(hold)).toEqual(["completed", "completed", "onHold", "pending", "pending"]);
  });

  it("marks a question left past its answer-by date overdue, never a hold", () => {
    const late = { due_on: "2026-10-15", business_days_left: -1, overdue: true };
    expect(stageChip(summary({ state: "INFO_REQUESTED", due: late }))).toBe("overdue");
    expect(stageChip(summary({ state: "INFO_REQUESTED" }))).toBe("onHold");
    expect(stageChip(summary({ state: "ON_HOLD", due: late }))).toBe("onHold");
  });

  it("ends an expiry in the group it stopped in, through an open question", () => {
    const events = history().events;
    const chain = [
      ...events,
      { ...events[1], id: "e3", seq: 3, command: "request_info", from_state: "UNDER_REVIEW" as const, to_state: "INFO_REQUESTED" as const },
      { ...events[1], id: "e4", seq: 4, command: "expire", actor_role: "system" as const, from_state: "INFO_REQUESTED" as const, to_state: "EXPIRED" as const },
    ];
    expect(stageLeft("EXPIRED", chain)).toBe("UNDER_REVIEW");
    const steps = stepperSteps({ state: "EXPIRED", stage_group: null, due: null, left: stageLeft("EXPIRED", chain) });
    expect(chips(steps)).toEqual(["ended", "pending", "pending", "pending", "pending"]);
  });

  it("says what the banner shows for each side state", () => {
    expect(sideBanner(detail({ state: "INFO_REQUESTED", notes: [asked] }))).toEqual({ kind: "info", question: asked });
    expect(sideBanner(detail({ state: "ON_HOLD", notes: [asked, answered, held] }))).toEqual({ kind: "hold", hold: held });
    expect(sideBanner(detail({ state: "EXPIRED", end_reason: "NO_REVIEW" }))).toEqual({ kind: "expired", reason: "NO_REVIEW" });
    expect(sideBanner(detail())).toBeNull();
  });

  it("says a question was answered only while the stage the answer resumed lasts", () => {
    const resumed = detail({ state: "UNDER_REVIEW", stage_entered_at: answered.at, notes: [asked, answered] });
    expect(sideBanner(resumed)).toEqual({ kind: "answered", answer: answered });
    expect(sideBanner({ ...resumed, state: "INTEREST_CONFIRMED", stage_entered_at: "2026-10-07T09:00:00Z" })).toBeNull();
    expect(sideBanner({ ...resumed, state: "DECLINED" })).toBeNull();
  });

  it("gives each side-state event its note, in order, leaving the system's resume without one", () => {
    const base = history().events[1];
    const events = [
      { ...base, id: "q1", seq: 3, command: "request_info" },
      { ...base, id: "a1", seq: 4, command: "answer_info" },
      { ...base, id: "h1", seq: 5, command: "pause" },
      { ...base, id: "r1", seq: 6, command: "resume", actor_role: "system" as const },
      { ...base, id: "h2", seq: 7, command: "pause" },
      { ...base, id: "r2", seq: 8, command: "resume" },
    ];
    const second = { ...held, body: "Board approval", resume_at: "2026-11-02" };
    const early = { kind: "resume" as const, body: "Approved early", by: "developer" as const, at: "2026-10-25T08:00:00Z", resume_at: null };
    const found = notesByEvent(events, [asked, answered, held, second, early]);
    expect(found.get("q1")).toBe(asked);
    expect(found.get("a1")).toBe(answered);
    expect(found.get("h1")).toBe(held);
    expect(found.has("r1")).toBe(false);
    expect(found.get("h2")).toBe(second);
    expect(found.get("r2")).toBe(early);
  });

  it("pairs notes on their event's seq when the API sends it, even against their order", () => {
    const base = history().events[1];
    const events = [
      { ...base, id: "h1", seq: 3, command: "pause" },
      { ...base, id: "r1", seq: 4, command: "resume" },
      { ...base, id: "h2", seq: 5, command: "pause" },
    ];
    // The notes arrive in the opposite order of their events: the seq decides, never the order.
    const second = { ...held, body: "Second hold", seq: 5 };
    const first = { ...held, body: "First hold", seq: 3 };
    const found = notesByEvent(events, [second, first]);
    expect(found.get("h1")).toBe(first);
    expect(found.get("h2")).toBe(second);
    expect(found.has("r1")).toBe(false);
    // A note naming no event of the list is shown nowhere; one without a seq takes the next unpaired event of its kind.
    const lost = { ...held, body: "Lost", seq: 99 };
    const unnumbered = { ...held, body: "Unnumbered", seq: null };
    const mixed = notesByEvent(events, [lost, unnumbered, second]);
    expect(mixed.get("h2")).toBe(second);
    expect(mixed.get("h1")).toBe(unnumbered);
  });

  it("builds the side states' requests on their routes, with their texts", () => {
    expect(commandRequest("request_info", "e1", 4, { input: { question: "Which co-ops?" } })).toEqual({
      path: "/api/engagements/{engagement_id}/request-info",
      params: { engagement_id: "e1" },
      body: { question: "Which co-ops?", lock_version: 4 },
    });
    expect(commandRequest("answer_info", "e1", 5, { input: { answer: "Two." } }).path).toBe("/api/engagements/{engagement_id}/answer-info");
    expect(commandRequest("cancel_request", "e1", 5).body).toEqual({ lock_version: 5 });
    expect(commandRequest("pause", "e1", 6, { input: { reason: "Budget", resume_at: "2026-10-21" } }).body).toEqual({
      reason: "Budget",
      resume_at: "2026-10-21",
      lock_version: 6,
    });
    expect(commandRequest("resume", "e1", 7, { input: { reason: "Approved" } }).path).toBe("/api/engagements/{engagement_id}/resume");
  });

  it("makes answering the awaited, primary step and keeps the organisation's withdrawal secondary", () => {
    const dev = actionItems(
      detail({ state: "INFO_REQUESTED", actions: ["answer_info", "withdraw"], awaiting: [{ command: "answer_info", party: "developer" }] }),
    );
    expect(dev.map((i) => [i.command, i.primary])).toEqual([
      ["answer_info", true],
      ["withdraw", false],
    ]);
    const org = actionItems(
      detail({ state: "INFO_REQUESTED", my_party: "org", actions: ["cancel_request"], awaiting: [{ command: "answer_info", party: "developer" }] }),
    );
    expect(org).toEqual([{ command: "cancel_request", primary: false }]);
  });

  it("writes a hold's dates", () => {
    expect(addDays("2026-10-02", 60)).toBe("2026-12-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
});
