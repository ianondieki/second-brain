import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { quizToday } from "@/test/quiz";
import { resolveServerTree } from "@/test/server-tree";

import type { QuizCalls } from "./calls";
import { FlagQuestion } from "./FlagQuestion";
import { OptIn } from "./board/OptIn";
import { QuizCard } from "./QuizCard";
import { QuizPlay } from "./QuizPlay";
import { QuizResults } from "./QuizResults";

// REQ-DEV-01 (P22-AF): Today's five on screen. The Home card in its three states (and left out), the play form (one
// primary action, inert until five answers; "Check 1, skip 4"; a day that ended), the results (score, marks in words,
// why, the source in a new tab, Flag), the flag sheet and the board's opt-in switch.

const router = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({ quizPlay: en.quizPlay }) }));

beforeAll(() => {
  // jsdom has no <dialog> methods: the sheet opens and closes as the browser's would.
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

function calls(overrides: Partial<QuizCalls> = {}): QuizCalls {
  return {
    finish: vi.fn(async () => ({ ok: true as const })),
    flag: vi.fn(async () => "sent" as const),
    optIn: vi.fn(async () => "ok" as const),
    ...overrides,
  };
}

const QUESTIONS = quizToday().questions.map(({ id, position, prompt, options, topic }) => ({ id, position, prompt, options, topic }));

describe("Home's Today's five card", () => {
  it("is one sentence and Play (a link, not the page's primary action) before playing", async () => {
    render(await resolveServerTree(await QuizCard({ state: { kind: "set", today: quizToday() } })));
    const card = document.querySelector("[data-home=quiz]")!;
    expect(within(card as HTMLElement).getByRole("heading", { name: "Today's five" })).toBeTruthy();
    expect(card.querySelector("[data-quiz-card=play]")).not.toBeNull();
    const play = screen.getByRole("link", { name: "Play" });
    expect(play.getAttribute("href")).toBe("/dev/quiz");
    expect(play.hasAttribute("data-primary")).toBe(false);
  });

  it("shows the score and the streak once played, with See why", async () => {
    render(await resolveServerTree(await QuizCard({ state: { kind: "set", today: quizToday({ played: true }) } })));
    expect(document.querySelector("[data-quiz-card=played]")?.textContent).toBe("3 of 5 today · 2-day streak");
    expect(screen.getByRole("link", { name: "See why" }).getAttribute("href")).toBe("/dev/quiz#quiz-results");
  });

  it("is one sentence and no action on a day without a set", async () => {
    render(await resolveServerTree(await QuizCard({ state: { kind: "none" } })));
    expect(screen.getByText("No quiz today, back tomorrow.")).toBeTruthy();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("is left out when the read failed", async () => {
    expect(await QuizCard({ state: null })).toBeNull();
  });
});

describe("the play form", () => {
  it("keeps Check answers inert until all five are answered, then sends them with the time", async () => {
    const given = calls();
    renderWithIntl(<QuizPlay setId="set-1" questions={QUESTIONS} calls={given} />);
    const check = screen.getByRole("button", { name: "Check answers" });
    expect(check.hasAttribute("data-primary")).toBe(true);
    expect(check.getAttribute("aria-disabled")).toBe("true");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getAllByRole("group")).toHaveLength(5);
    // Topic as plain text, never a chip.
    expect(screen.getByText("Topic 1").closest("[data-chip]")).toBeNull();

    fireEvent.click(check);
    expect(given.finish).not.toHaveBeenCalled();
    expect(document.activeElement?.getAttribute("name")).toBe("q1");

    for (const [index, question] of QUESTIONS.entries()) {
      fireEvent.click(within(screen.getByRole("group", { name: question.prompt })).getAllByRole("radio")[index % 4]);
    }
    expect(screen.getByText("5 of 5 answered")).toBeTruthy();
    expect(check.getAttribute("aria-disabled")).toBeNull();
    await act(async () => fireEvent.click(check));
    expect(given.finish).toHaveBeenCalledWith("set-1", [0, 1, 2, 3, 0], expect.any(Number));
    await waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1));
  });

  it("says how to check before anything is answered, then offers to check what is answered and skip the rest", async () => {
    const given = calls();
    renderWithIntl(<QuizPlay setId="set-1" questions={QUESTIONS} calls={given} />);
    expect(screen.queryByRole("button", { name: /skip/ })).toBeNull();
    expect(document.getElementById("quiz-check-hint")?.textContent).toBe("Answer all five to check them.");
    fireEvent.click(within(screen.getByRole("group", { name: QUESTIONS[1].prompt })).getAllByRole("radio")[2]);
    expect(document.getElementById("quiz-check-hint")?.textContent).toBe("Answer all five to check them, or skip the rest.");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Check 1, skip 4" })));
    expect(given.finish).toHaveBeenCalledWith("set-1", [null, 2, null, null, null], expect.any(Number));
  });

  it("is one sentence when the day ended meanwhile, and says a failure without losing the answers", async () => {
    const closed = calls({ finish: vi.fn(async () => ({ ok: false as const, problem: "closed" as const })) });
    renderWithIntl(<QuizPlay setId="set-1" questions={QUESTIONS} calls={closed} />);
    fireEvent.click(within(screen.getByRole("group", { name: QUESTIONS[0].prompt })).getAllByRole("radio")[0]);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Check 1, skip 4" })));
    expect(document.querySelector("[data-quiz-ended=closed]")?.textContent).toBe(en.quizPlay.problem.closed);
    expect(screen.getByRole("link", { name: "Go to Home" }).getAttribute("href")).toBe("/dev");
    expect(screen.queryByRole("group")).toBeNull();
    expect(router.refresh).not.toHaveBeenCalled();
    cleanup();

    const failing = calls({ finish: vi.fn(async () => ({ ok: false as const, problem: "network" as const })) });
    renderWithIntl(<QuizPlay setId="set-1" questions={QUESTIONS} calls={failing} />);
    fireEvent.click(within(screen.getByRole("group", { name: QUESTIONS[0].prompt })).getAllByRole("radio")[3]);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Check 1, skip 4" })));
    expect(screen.getByRole("alert").textContent).toBe(en.quizPlay.problem.network);
    expect((within(screen.getByRole("group", { name: QUESTIONS[0].prompt })).getAllByRole("radio")[3] as HTMLInputElement).checked).toBe(true);
  });
});

describe("the results", () => {
  it("shows the score, each question's marks in words, why and the source in a new tab", async () => {
    const today = quizToday({ played: true, answers: [2, 0, 2, null, 0], pulled: 2 });
    render(await resolveServerTree(await QuizResults({ today, attempt: today.attempt! })));
    expect(document.querySelector("[data-quiz-score]")?.textContent).toBe("2 of 4 right");
    expect(document.querySelector("[data-quiz-streak]")?.textContent).toBe("2-day streak. Your best: 5 days.");
    expect(screen.getByRole("heading", { level: 2, name: "Your answers" }).getAttribute("tabindex")).toBe("-1");

    const first = document.querySelector("[data-result='1']")!;
    expect(first.querySelector("[data-mark=rightChosen]")?.textContent).toContain("Your answer, right");
    const second = document.querySelector("[data-result='2']")!;
    expect(second.querySelector("[data-mark=wrongChosen]")?.textContent).toContain("Your answer");
    expect(second.querySelector("[data-mark=right]")?.textContent).toContain("Right answer");
    expect(second.querySelector("[data-why]")?.textContent).toBe("Because of reason 2.");
    const source = within(second as HTMLElement).getByRole("link", { name: /Official page 2/ });
    expect(source.getAttribute("target")).toBe("_blank");
    expect(source.getAttribute("rel")).toContain("noopener");
    expect(source.textContent).toContain("(opens in a new tab)");

    // A withdrawn question says so, carries no marks and cannot be flagged; a skipped one says it was skipped.
    const third = document.querySelector("[data-result='3']")!;
    expect(third.textContent).toContain(en.quiz.results.pulled);
    expect(third.querySelector("[data-mark]")).toBeNull();
    expect(third.querySelector("[data-flag-open]")).toBeNull();
    expect(document.querySelector("[data-result='4']")?.textContent).toContain(en.quiz.results.skipped);
    // A source that is not plain https is never a link.
    expect(within(document.querySelector("[data-result='5']") as HTMLElement).queryByRole("link")).toBeNull();
    expect(screen.getAllByRole("button", { name: /^Flag question/ })).toHaveLength(4);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "See this week's board" }).getAttribute("href")).toBe("/dev/quiz/board");
  });
});

describe("the flag sheet", () => {
  it("asks for a reason, sends it with the note, then thanks in the button's place with focus", async () => {
    const given = calls();
    renderWithIntl(<FlagQuestion questionId="q-2" number={2} calls={given} />);
    fireEvent.click(screen.getByRole("button", { name: "Flag question 2" }));
    const sheet = screen.getByRole("dialog", { name: "Flag question 2" });
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send" })));
    expect(given.flag).not.toHaveBeenCalled();
    expect(within(sheet).getByText("Choose what is wrong.")).toBeTruthy();

    fireEvent.click(within(sheet).getByRole("radio", { name: "The answer is wrong" }));
    fireEvent.change(within(sheet).getByRole("textbox", { name: "Note (optional)" }), { target: { value: "It is 3" } });
    await act(async () => fireEvent.click(within(sheet).getByRole("button", { name: "Send" })));
    expect(given.flag).toHaveBeenCalledWith("q-2", "wrong_answer", "It is 3");
    const said = screen.getByRole("status");
    expect(said.textContent).toBe("Thanks, we'll look.");
    await waitFor(() => expect(document.activeElement).toBe(said));
    expect(screen.queryByRole("button", { name: "Flag question 2" })).toBeNull();
  });

  it("says an earlier flag in place, and the daily limit inside the sheet", async () => {
    renderWithIntl(<FlagQuestion questionId="q-1" number={1} calls={calls({ flag: vi.fn(async () => "already" as const) })} />);
    fireEvent.click(screen.getByRole("button", { name: "Flag question 1" }));
    fireEvent.click(screen.getByRole("radio", { name: "Something else" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    expect(screen.getByRole("status").textContent).toBe("You already flagged this.");
    cleanup();

    renderWithIntl(<FlagQuestion questionId="q-1" number={1} calls={calls({ flag: vi.fn(async () => "limit" as const) })} />);
    fireEvent.click(screen.getByRole("button", { name: "Flag question 1" }));
    fireEvent.click(screen.getByRole("radio", { name: "It is out of date" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    expect(screen.getByRole("alert").textContent).toBe(en.quizPlay.flag.outcome.limit);
    expect(screen.getByRole("dialog").hasAttribute("open")).toBe(true);
  });
});

describe("the board's opt-in switch", () => {
  it("explains who sees what, keeps the choice and fetches the board again", async () => {
    const given = calls();
    renderWithIntl(<OptIn initial={false} calls={given} />);
    const toggle = screen.getByRole("switch", { name: "Show me on the board" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(document.getElementById(toggle.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Your handle and this week's points are shown to other developers. Never to organisations.",
    );
    await act(async () => fireEvent.click(toggle));
    expect(given.optIn).toHaveBeenCalledWith(true);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("status").textContent).toBe("You are on the board.");
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("turns back and says so when the choice was not kept, or the session ended", async () => {
    for (const outcome of ["failed", "signedOut"] as const) {
      renderWithIntl(<OptIn initial calls={calls({ optIn: vi.fn(async () => outcome) })} />);
      const toggle = screen.getByRole("switch", { name: "Show me on the board" });
      await act(async () => fireEvent.click(toggle));
      expect(toggle.getAttribute("aria-checked")).toBe("true");
      expect(screen.getByRole("alert").textContent).toBe(en.quizPlay.optIn[outcome]);
      expect(router.refresh).not.toHaveBeenCalled();
      cleanup();
    }
  });
});
