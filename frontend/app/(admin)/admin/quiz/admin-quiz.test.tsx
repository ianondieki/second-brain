import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { AdminQuizCalls, Outcome } from "./calls";
import { QuestionActions } from "./QuestionActions";
import {
  averageScore,
  isDayOver,
  nairobiDay,
  pulledBecause,
  questionRefusal,
  queue,
  refusalNext,
  refusalOf,
  type QuizSetSummary,
} from "./quiz";
import { SetDecision } from "./SetDecision";

// REQ-DEV-01 (P22-AF): the staff quiz screens. The queue's order, the stats and refusals in words, the decision
// behind a confirmation and the step-up, and Pull (with a reason) / Restore per question.

const router = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
// The console's step-up call (research/calls.ts): a fresh code is accepted.
const confirmStepUp = vi.hoisted(() => vi.fn(async () => ({ ok: true as const })));
vi.mock("../research/calls", () => ({ confirmStepUp }));

/** Enters a fresh code in the step-up form and confirms it. */
async function stepUp() {
  fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => router.refresh.mockReset());
afterEach(cleanup);

const err = (code: string) => ({ detail: { code, message: "x" } });

function summary(quiz_date: string, status: QuizSetSummary["status"]): QuizSetSummary {
  return { id: `${quiz_date}-${status}`, quiz_date, status, origin: "model", flags: 0, pulled: 0, created_at: "2026-10-04T23:30:00Z" };
}

function calls(overrides: Partial<AdminQuizCalls> = {}): AdminQuizCalls {
  return {
    decide: vi.fn(async () => ({ ok: true, data: { status: "approved" } }) as Outcome<{ status: string }>),
    pull: vi.fn(async () => ({ ok: true, data: { rescored: 3 } }) as Outcome<{ rescored: number }>),
    restore: vi.fn(async () => ({ ok: true, data: { rescored: 2 } }) as Outcome<{ rescored: number }>),
    ...overrides,
  };
}

describe("the quiz queue's rules", () => {
  it("lists drafts first, oldest day first, then decided sets newest first", () => {
    const { waiting, decided } = queue([
      summary("2026-10-03", "approved"),
      summary("2026-10-06", "draft"),
      summary("2026-10-05", "draft"),
      summary("2026-10-04", "rejected"),
    ]);
    expect(waiting.map((s) => s.quiz_date)).toEqual(["2026-10-05", "2026-10-06"]);
    expect(decided.map((s) => s.quiz_date)).toEqual(["2026-10-04", "2026-10-03"]);
  });

  it("writes the average only from three plays on (the API sends none before)", () => {
    expect(averageScore("en", "3.67")).toBe("3.67");
    expect(averageScore("en", "4.00")).toBe("4");
    expect(averageScore("en", null)).toBeNull();
  });

  it("says why a question was pulled: three flags, or the staff member's reason", () => {
    expect(pulledBecause({ status: "pulled", pulled_reason: "three_flags" })).toEqual({ byFlags: true });
    expect(pulledBecause({ status: "pulled", pulled_reason: "Two right answers" })).toEqual({ reason: "Two right answers" });
    expect(pulledBecause({ status: "live", pulled_reason: null })).toBeNull();
  });

  it("knows a draft whose Nairobi day is over", () => {
    expect(nairobiDay(new Date("2026-10-05T21:30:00Z"))).toBe("2026-10-06");
    expect(isDayOver(summary("2026-10-05", "draft"), "2026-10-06")).toBe(true);
    expect(isDayOver(summary("2026-10-06", "draft"), "2026-10-06")).toBe(false);
    expect(isDayOver(summary("2026-10-05", "approved"), "2026-10-06")).toBe(false);
  });

  it("maps each refusal to its sentence and what it leaves", () => {
    expect(refusalOf(403, err("step_up_required"))).toEqual({ kind: "stepUp" });
    expect(refusalOf(409, err("day_over"))).toEqual({ kind: "refusal", code: "day_over" });
    expect(refusalOf(404, err("not_found"))).toEqual({ kind: "refusal", code: "not_found" });
    expect(refusalOf(403, err("forbidden"))).toEqual({ kind: "refusal", code: "forbidden" });
    expect(refusalOf(500, undefined)).toEqual({ kind: "refusal", code: "generic" });
    expect(refusalOf(401, err("unauthenticated"))).toEqual({ kind: "refusal", code: "signedOut" });
    expect(questionRefusal("not_found")).toBe("question_not_found");
    expect(questionRefusal("already_live")).toBe("already_live");
    expect(refusalNext("day_over")).toBe("reject");
    expect(refusalNext("incomplete_set")).toBe("reject");
    expect(refusalNext("already_decided")).toBe("reload");
    expect(refusalNext("generic")).toBe("retry");
  });
});

describe("the set decision", () => {
  it("approves after a confirmation that says when developers see it", async () => {
    const given = calls();
    renderWithIntl(<SetDecision setId="set-1" day="6 Oct 2026" calls={given} />);
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve.hasAttribute("data-primary")).toBe(true);
    fireEvent.click(approve);
    const dialog = screen.getByRole("dialog", { name: "Approve this set?" });
    expect(dialog.textContent).toContain("Developers see these five questions on 6 Oct 2026.");
    expect(given.decide).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Approve" })));
    expect(given.decide).toHaveBeenCalledWith("set-1", "approve");
    expect(screen.getByRole("status").textContent).toBe("Approved. Developers see it on 6 Oct 2026.");
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("asks for a fresh code in place, then repeats the decision", async () => {
    const decide = vi
      .fn<AdminQuizCalls["decide"]>()
      .mockResolvedValueOnce({ ok: false, refusal: { kind: "stepUp" } })
      .mockResolvedValueOnce({ ok: true, data: { status: "rejected" } });
    renderWithIntl(<SetDecision setId="set-1" day="6 Oct 2026" calls={calls({ decide })} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = screen.getByRole("dialog", { name: "Reject this set?" });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Reject" })));
    expect(document.querySelector("[data-step-up]")).not.toBeNull();
    expect(decide).toHaveBeenCalledTimes(1);
    await stepUp();
    expect(confirmStepUp).toHaveBeenCalledWith("123456");
    expect(decide).toHaveBeenCalledTimes(2);
    expect(decide).toHaveBeenLastCalledWith("set-1", "reject");
    expect(screen.getByRole("status").textContent).toBe("Rejected. No one will see it.");
  });

  it("starts a draft whose day is over with Reject as the one primary action", () => {
    renderWithIntl(<SetDecision setId="set-1" day="4 Oct 2026" dayOver calls={calls()} />);
    expect(document.querySelector("[data-day-over]")?.textContent).toBe("This day is over; it can only be rejected.");
    expect(screen.getByRole("button", { name: "Approve" }).getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("leaves only Reject, as the primary action, on a day that is over", async () => {
    const decide = vi.fn<AdminQuizCalls["decide"]>(async () => ({ ok: false, refusal: { kind: "refusal", code: "day_over" } }));
    renderWithIntl(<SetDecision setId="set-1" day="4 Oct 2026" calls={calls({ decide })} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await act(async () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve" })));
    expect(screen.getByRole("alert").textContent).toBe("This day is over; it can only be rejected.");
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve.getAttribute("aria-disabled")).toBe("true");
    expect(approve.hasAttribute("data-primary")).toBe(false);
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
    fireEvent.click(approve);
    expect(screen.getByRole("dialog", { hidden: true }).hasAttribute("open")).toBe(false);
  });
});

describe("pulling and restoring a question", () => {
  it("needs a reason to pull, sends it, and says how many plays were scored again", async () => {
    const given = calls();
    renderWithIntl(<QuestionActions questionId="q-3" number={3} status="live" calls={given} />);
    fireEvent.click(screen.getByRole("button", { name: "Pull question 3" }));
    const dialog = screen.getByRole("dialog", { name: "Pull question 3?" });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pull question" })));
    expect(given.pull).not.toHaveBeenCalled();
    expect(within(dialog).getByText("Say why it is pulled.")).toBeTruthy();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Why it is pulled" }), { target: { value: "Two options are right" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pull question" })));
    expect(given.pull).toHaveBeenCalledWith("q-3", "Two options are right");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Pulled. Plays scored again: 3."));
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("asks for a fresh code before a pull, then repeats it; cancelling gives focus back to Pull", async () => {
    const pull = vi
      .fn<AdminQuizCalls["pull"]>()
      .mockResolvedValueOnce({ ok: false, refusal: { kind: "stepUp" } })
      .mockResolvedValueOnce({ ok: false, refusal: { kind: "stepUp" } })
      .mockResolvedValueOnce({ ok: true, data: { rescored: 1 } });
    renderWithIntl(<QuestionActions questionId="q-2" number={2} status="live" calls={calls({ pull })} />);
    const ask = async () => {
      fireEvent.click(screen.getByRole("button", { name: "Pull question 2" }));
      const dialog = screen.getByRole("dialog", { name: "Pull question 2?" });
      fireEvent.change(within(dialog).getByRole("textbox", { name: "Why it is pulled" }), { target: { value: "Outdated" } });
      await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pull question" })));
    };
    await ask();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Pull question 2" })));

    await ask();
    await stepUp();
    expect(pull).toHaveBeenCalledTimes(3);
    expect(pull).toHaveBeenLastCalledWith("q-2", "Outdated");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Pulled. Plays scored again: 1."));
  });

  it("names the question when a pull finds it gone", async () => {
    const pull = vi.fn<AdminQuizCalls["pull"]>(async () => ({ ok: false, refusal: { kind: "refusal", code: "not_found" } }));
    renderWithIntl(<QuestionActions questionId="q-2" number={2} status="live" calls={calls({ pull })} />);
    fireEvent.click(screen.getByRole("button", { name: "Pull question 2" }));
    const dialog = screen.getByRole("dialog", { name: "Pull question 2?" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Why it is pulled" }), { target: { value: "Wrong" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pull question" })));
    expect(screen.getByRole("alert").textContent).toBe("This question no longer exists.");
  });

  it("restores a pulled question after a confirmation, and says when it was already live", async () => {
    const restore = vi.fn<AdminQuizCalls["restore"]>(async () => ({ ok: false, refusal: { kind: "refusal", code: "already_live" } }));
    renderWithIntl(<QuestionActions questionId="q-3" number={3} status="pulled" calls={calls({ restore })} />);
    fireEvent.click(screen.getByRole("button", { name: "Restore question 3" }));
    const dialog = screen.getByRole("dialog", { name: "Restore question 3?" });
    expect(dialog.textContent).toContain("flags never pull it again");
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Restore question" })));
    expect(restore).toHaveBeenCalledWith("q-3");
    expect(screen.getByRole("alert").textContent).toBe("This question is already live.");
  });
});
