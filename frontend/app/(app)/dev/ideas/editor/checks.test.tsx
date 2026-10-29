import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { PROPOSAL_ID, refusal, SERVER_MESSAGE, type FakeAnswer } from "@/test/assistant";
import {
  BY_MODEL,
  BY_RULES,
  CLEAR,
  checksCalls,
  DEMO_CLEAR,
  HIGH_DEMO,
  httpChecks,
  NONE,
  SOME,
  UNCHECKED,
} from "@/test/checks";
import { calls, READY, renderEditor, SAVED, settleLazy } from "@/test/ideas-editor";

import type { CheckOutcome, Originality } from "../checks";
import { EMPTY_STATE } from "../versions";
import { CheckAnswer } from "./CheckAnswer";
import { preloadChecks } from "./Editor";

// P19-F (REQ-PROP-04 originality, REQ-REPO-01 over-disclosure, warn only): the editor's "Teaser checks" card. Two
// secondary buttons, each answering in place in a polite live region (role=status, never an alert, never the primary
// action); the overlap answer is a band in words with the AI labels as the assistant draws them; the over-disclosure
// answer names the fields in words; every refusal has its fixed sentence and the API's messages are never shown.

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

beforeAll(async () => {
  await preloadChecks(); // the card's chunk, loaded before a render as the browser loads it on the first press
});

afterEach(() => cleanup());

const OVERLAP = "Check overlap";
const DISCLOSURE = "Check what it gives away";
const region = (kind: "overlap" | "disclosure") => document.querySelector<HTMLElement>(`[data-check='${kind}']`)!;
const chips = (kind: "overlap" | "disclosure") =>
  [...region(kind).querySelectorAll("[data-chip]")].map((chip) => chip.textContent);

async function press(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

async function check(name: string, fake: ReturnType<typeof checksCalls> | ReturnType<typeof httpChecks>["calls"]) {
  await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: fake });
  await press(name);
}

describe("closed", () => {
  it("is a quiet card of two secondary buttons that send nothing until pressed", async () => {
    const fake = checksCalls();
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: fake });
    const card = screen.getByRole("region", { name: "Teaser checks" });
    // A magnifier beside the heading, never a tick: nothing has passed before a check runs.
    const heading = within(card).getByRole("heading", { name: "Teaser checks" });
    expect(heading.querySelector("svg")?.getAttribute("data-icon")).toBe("look");
    expect(heading.querySelectorAll("svg")).toHaveLength(1);
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([OVERLAP, DISCLOSURE]);
    for (const button of buttons) {
      expect(button.hasAttribute("data-primary")).toBe(false);
      expect(button.getAttribute("type")).toBe("button"); // native: Enter and Space press it
      expect(button.getAttribute("tabindex")).toBeNull();
    }
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1); // "Continue" stays the one primary action
    expect(fake.overlap).not.toHaveBeenCalled();
    expect(fake.disclosure).not.toHaveBeenCalled();
  });

  it("sits after the teaser and before the writing assistant", async () => {
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: checksCalls() });
    const cards = [...document.querySelectorAll("section[aria-labelledby$='-title']")];
    expect(cards.map((card) => card.getAttribute("aria-labelledby"))).toEqual(["teaser-title", "checks-title", "assistant-title"]);
  });
});

describe("check overlap", () => {
  it("answers in a polite live region, says how many it compared with, and keeps focus on the button", async () => {
    const fake = checksCalls();
    await check(OVERLAP, fake);
    expect(fake.overlap).toHaveBeenCalledWith(PROPOSAL_ID);
    const status = region("overlap");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.textContent).toBe("No overlap with other published ideas (compared with 12).");
    expect(chips("overlap")).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: OVERLAP }));
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("says when there is nothing to compare with yet", async () => {
    await check(OVERLAP, checksCalls({ overlap: vi.fn(async () => ({ ok: true as const, value: { ...NONE, compared: 0 } })) }));
    expect(region("overlap").textContent).toBe("No other published ideas to compare with yet.");
  });

  it("words some overlap with the explainer sentence, labelled AI-drafted", async () => {
    await check(OVERLAP, checksCalls({ overlap: vi.fn(async () => ({ ok: true as const, value: SOME })) }));
    const status = region("overlap");
    expect(status.textContent).toContain(
      "Some overlap with another published idea. Saying what makes yours different can help.",
    );
    expect(status.textContent).toContain(SOME.explanation);
    expect(chips("overlap")).toEqual(["AI-drafted"]);
  });

  it("words high overlap as no judgement, and labels the demo fallback", async () => {
    await check(OVERLAP, checksCalls({ overlap: vi.fn(async () => ({ ok: true as const, value: HIGH_DEMO })) }));
    expect(region("overlap").querySelector("p")!.textContent).toBe(
      "High overlap: your teaser reads close to another published idea. That is not a judgement; it is worth a look at what makes yours different.",
    );
    expect(chips("overlap")).toEqual(["Demo fallback"]);
  });

  it("never shows a score, and at most the two AI labels", async () => {
    const both: Originality = { ...SOME, band: "high_overlap", demo_fallback: true, compared: 7 };
    await check(OVERLAP, checksCalls({ overlap: vi.fn(async () => ({ ok: true as const, value: both })) }));
    expect(chips("overlap")).toEqual(["AI-drafted", "Demo fallback"]);
    expect(region("overlap").textContent).not.toMatch(/\d/); // the count shows only with "no overlap"
  });

  it("is busy while it runs: the button ignores presses and the region says it is comparing", async () => {
    let release: (value: CheckOutcome<Originality>) => void = () => {};
    const fake = checksCalls({
      overlap: vi.fn(() => new Promise<CheckOutcome<Originality>>((resolve) => (release = resolve))),
    });
    await check(OVERLAP, fake);
    const button = screen.getByRole("button", { name: OVERLAP });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(region("overlap").textContent).toBe("Comparing your teaser with other published ideas…");
    await press(OVERLAP);
    expect(fake.overlap).toHaveBeenCalledTimes(1);
    // The other check stays free.
    expect(screen.getByRole("button", { name: DISCLOSURE }).getAttribute("aria-disabled")).toBeNull();
    await act(async () => release({ ok: true, value: NONE }));
    expect(button.getAttribute("aria-disabled")).toBeNull();
    expect(region("overlap").textContent).toContain("No overlap");
  });

  it("runs again on a second press and shows only the new answer", async () => {
    const fake = checksCalls({
      overlap: vi
        .fn()
        .mockResolvedValueOnce({ ok: true, value: SOME })
        .mockResolvedValueOnce({ ok: true, value: NONE }),
    });
    await check(OVERLAP, fake);
    await press(OVERLAP);
    expect(fake.overlap).toHaveBeenCalledTimes(2);
    expect(region("overlap").textContent).toBe("No overlap with other published ideas (compared with 12).");
  });
});

describe("check what it gives away", () => {
  it("names the fields in words and gives the fixed advice for the rules' answer (never the API's words)", async () => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: BY_RULES })) }));
    const status = region("disclosure");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.querySelector("p")!.textContent).toBe(
      "This reads like how it works, not what it does: summary and the problem it solves.",
    );
    expect(status.textContent).toContain("Methods, tools and code belong in the full details, which stay confidential.");
    expect(status.textContent).not.toContain(BY_RULES.why);
    expect(chips("disclosure")).toEqual([]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  // Every field label reads after the sentence, an article in it or not (P19 reviewer round, MAJOR 1).
  it.each([
    [["problem_statement"], "This reads like how it works, not what it does: the problem it solves."],
    [["title", "problem_statement"], "This reads like how it works, not what it does: title and the problem it solves."],
  ] as const)("names %j after the sentence, so the label reads", async (fields, sentence) => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: { ...BY_RULES, fields: [...fields] } })) }));
    expect(region("disclosure").querySelector("p")!.textContent).toBe(sentence);
  });

  it("shows the model's reason, labelled AI-drafted", async () => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: BY_MODEL })) }));
    expect(region("disclosure").querySelector("p")!.textContent).toBe("This reads like how it works, not what it does: expected impact.");
    expect(region("disclosure").textContent).toContain(BY_MODEL.why);
    expect(chips("disclosure")).toEqual(["AI-drafted"]);
  });

  it("says nothing gives away how it works", async () => {
    await check(DISCLOSURE, checksCalls());
    expect(region("disclosure").textContent).toBe("Nothing gives away how it works.");
    expect(region("disclosure").querySelector("[data-check-answer='clear']")).not.toBeNull();
  });

  it("labels the demo fallback and does not claim the teaser was read by a model", async () => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: DEMO_CLEAR })) }));
    expect(region("disclosure").querySelector("p")!.textContent).toBe(
      "No AI model is connected in this demo. The quick check looks only for common giveaways, such as code, file names and tool names, and found none.",
    );
    expect(chips("disclosure")).toEqual(["Demo fallback"]);
    expect(region("disclosure").textContent).not.toContain(DEMO_CLEAR.why);
  });

  it("says the teaser could not be checked when there is no answer", async () => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: UNCHECKED })) }));
    expect(region("disclosure").textContent).toBe(
      "The teaser could not be checked this time. Look over the text, then try again.",
    );
    expect(region("disclosure").textContent).not.toContain(UNCHECKED.why);
  });

  it("never blocks the rest of the editor: Continue is still the one primary action", async () => {
    await check(DISCLOSURE, checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: BY_RULES })) }));
    const primary = document.querySelectorAll("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Continue");
    expect(primary[0].getAttribute("aria-disabled")).toBeNull();
  });
});

describe("before checking", () => {
  it("asks for the teaser first, and sends nothing", async () => {
    const fake = checksCalls();
    const editor = calls();
    await renderEditor({ id: PROPOSAL_ID, initial: EMPTY_STATE, checks: fake, calls: editor });
    await press(OVERLAP);
    await press(DISCLOSURE);
    expect(region("overlap").textContent).toBe("Write the teaser first, then check it.");
    expect(region("disclosure").textContent).toBe("Write the teaser first, then check it.");
    expect(fake.overlap).not.toHaveBeenCalled();
    expect(fake.disclosure).not.toHaveBeenCalled();
    expect(editor.saveState).not.toHaveBeenCalled();
  });

  it("saves what was typed first, and checks nothing when the save is refused", async () => {
    const fake = checksCalls();
    const editor = calls({
      saveState: vi.fn(async () => ({
        outcome: { ok: false as const, problem: "fields" as const, fields: [{ field: "summary" as const, code: "contains_email" }] },
        held: [],
      })),
    });
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: fake, calls: editor });
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "Write to jane@example.com" } });
    await press(OVERLAP);
    await waitFor(() =>
      expect(region("overlap").textContent).toBe(
        "Your latest changes are not saved, so nothing was checked. Fix any marked fields, then try again.",
      ),
    );
    expect(fake.overlap).not.toHaveBeenCalled();
  });

  it("makes the draft of a new idea first, then checks it", async () => {
    const fake = checksCalls();
    const editor = calls();
    await renderEditor({ id: null, initial: READY, checks: fake, calls: editor });
    await press(DISCLOSURE);
    await waitFor(() => expect(fake.disclosure).toHaveBeenCalledWith(SAVED.id));
    expect(editor.saveState).toHaveBeenCalledTimes(1);
  });
});

describe("refusals", () => {
  const OVERLAP_PATH = `POST /api/me/proposals/${PROPOSAL_ID}/originality`;
  const DISCLOSURE_PATH = `POST /api/me/proposals/${PROPOSAL_ID}/disclosure-check`;
  const CASES: Array<[string, string, FakeAnswer, string]> = [
    ["the daily limit", OVERLAP, { status: 429, body: refusal("originality_limit") }, "You have used today’s overlap checks; they come back at midnight Nairobi time."],
    ["429 originality_busy", OVERLAP, { status: 429, body: refusal("originality_busy") }, "The overlap check is still running. Try again in a moment."],
    ["409 proposal_hidden", OVERLAP, { status: 409, body: refusal("proposal_hidden") }, "This idea was deleted, so it cannot be checked."],
    // Another owner's idea answers 404 like an unknown one (bridge/proposals/originality.owned_by).
    ["404 not_found (another owner's idea, or none)", OVERLAP, { status: 404, body: refusal("not_found") }, "This idea is not one of yours, or it was deleted."],
    ["404 not_found on the disclosure check", DISCLOSURE, { status: 404, body: refusal("not_found") }, "This idea is not one of yours, or it was deleted."],
    ["401", OVERLAP, { status: 401, body: refusal("unauthenticated") }, "Your session has ended. Log in again, then come back to this idea."],
    ["a plain 429", OVERLAP, { status: 429, body: refusal("rate_limited") }, "Too many attempts. Wait a minute, then try again."],
    ["503 without a code", OVERLAP, { status: 503, body: { detail: "Service Unavailable" } }, "The check could not finish just now. Try again later."],
    ["a lost connection", OVERLAP, "offline", "We could not reach the server. Check your connection, then try again."],
    ["500", OVERLAP, { status: 500, body: refusal("internal") }, "Something went wrong. Try again in a moment."],
    ["429 disclosure_busy", DISCLOSURE, { status: 429, body: refusal("disclosure_busy") }, "The teaser check is still running. Try again in a moment."],
    ["429 disclosure_rate_limited", DISCLOSURE, { status: 429, body: refusal("disclosure_rate_limited") }, "You have run many teaser checks today. Try again tomorrow."],
    ["429 assistant_budget", DISCLOSURE, { status: 429, body: refusal("assistant_budget") }, "You have used this month's writing assistant allowance."],
    ["503 assistant_paused", DISCLOSURE, { status: 503, body: refusal("assistant_paused") }, "The writing assistant is paused for today. Try again tomorrow."],
    ["503 assistant_off", DISCLOSURE, { status: 503, body: refusal("assistant_off") }, "The writing assistant is switched off for now."],
  ];

  it.each(CASES)("%s has its own fixed sentence, politely, with the button kept", async (_, name, answer, sentence) => {
    const kind = name === OVERLAP ? "overlap" : "disclosure";
    const http = httpChecks({ [kind === "overlap" ? OVERLAP_PATH : DISCLOSURE_PATH]: [answer] });
    await check(name, http.calls);
    await waitFor(() => expect(region(kind).textContent).toBe(sentence));
    expect(region(kind).getAttribute("role")).toBe("status");
    // A daily limit is a fact, not a failure: a note, without the error mark.
    const limit = _ === "the daily limit" || _ === "429 disclosure_rate_limited";
    expect(region(kind).querySelector(`[data-check-answer='${limit ? "note" : "problem"}']`)).not.toBeNull();
    if (limit) expect(region(kind).querySelector(".text-error")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.body.textContent).not.toContain(SERVER_MESSAGE);
    expect(document.activeElement).toBe(screen.getByRole("button", { name }));
  });

  it("says the overlap limit under Check overlap only, while the teaser check still runs", async () => {
    const http = httpChecks({
      [OVERLAP_PATH]: [{ status: 429, body: refusal("originality_limit") }],
      [DISCLOSURE_PATH]: [{ status: 200, body: CLEAR }],
    });
    await check(OVERLAP, http.calls);
    await waitFor(() => expect(region("overlap").textContent).toContain("today’s overlap checks"));
    expect(region("disclosure").textContent).toBe("");
    await press(DISCLOSURE);
    await waitFor(() => expect(region("disclosure").textContent).toBe("Nothing gives away how it works."));
    expect(region("overlap").textContent).toContain("today’s overlap checks");
  });

  it("over HTTP: one POST to each route, nothing else", async () => {
    const http = httpChecks({
      [OVERLAP_PATH]: [{ status: 200, body: NONE }],
      [DISCLOSURE_PATH]: [{ status: 200, body: CLEAR }],
    });
    await check(OVERLAP, http.calls);
    await waitFor(() => expect(region("overlap").textContent).toContain("No overlap"));
    await press(DISCLOSURE);
    await waitFor(() => expect(region("disclosure").textContent).toBe("Nothing gives away how it works."));
    expect(http.seen.map(({ method, path }) => `${method} ${path}`)).toEqual([OVERLAP_PATH, DISCLOSURE_PATH]);
  });
});

describe("today's last check", () => {
  const last = <CheckAnswer tone="note" sentence="Server-drawn overlap answer" caption="From your last check today." />;

  it("shows the server's answer before anything is pressed, and keeps it while the other check runs", async () => {
    const fake = checksCalls();
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: fake, lastOverlap: last });
    expect(screen.getByText("Server-drawn overlap answer")).toBeTruthy();
    expect(screen.getByText("From your last check today.")).toBeTruthy();
    await press(DISCLOSURE);
    expect(region("overlap").textContent).toContain("Server-drawn overlap answer");
    expect(fake.overlap).not.toHaveBeenCalled();
  });

  it("gives way to a new overlap answer", async () => {
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: checksCalls(), lastOverlap: last });
    await press(OVERLAP);
    expect(screen.queryByText("Server-drawn overlap answer")).toBeNull();
    expect(region("overlap").textContent).toBe("No overlap with other published ideas (compared with 12).");
  });
});

describe("across the steps", () => {
  it("keeps a running check busy on the redrawn card, and its answer arrives there", async () => {
    let release: (value: CheckOutcome<Originality>) => void = () => {};
    const fake = checksCalls({
      overlap: vi.fn(() => new Promise<CheckOutcome<Originality>>((resolve) => (release = resolve))),
    });
    await check(OVERLAP, fake);
    await press("Continue");
    await settleLazy();
    await press("Back");
    // A new card: the check still runs, so its button is busy and a press sends nothing more.
    expect(region("overlap").textContent).toBe("Comparing your teaser with other published ideas…");
    expect(screen.getByRole("button", { name: OVERLAP }).getAttribute("aria-disabled")).toBe("true");
    await press(OVERLAP);
    expect(fake.overlap).toHaveBeenCalledTimes(1);
    await act(async () => release({ ok: true, value: SOME }));
    expect(region("overlap").textContent).toContain("Some overlap with another published idea.");
    expect(screen.getByRole("button", { name: OVERLAP }).getAttribute("aria-disabled")).toBeNull();
    expect(chips("overlap")).toEqual(["AI-drafted"]);
  });

  it("shows on the redrawn card an answer that arrived while the owner was on another step", async () => {
    let release: (value: CheckOutcome<Originality>) => void = () => {};
    const fake = checksCalls({
      overlap: vi.fn(() => new Promise<CheckOutcome<Originality>>((resolve) => (release = resolve))),
    });
    await check(OVERLAP, fake);
    await press("Continue");
    await settleLazy();
    await act(async () => release({ ok: true, value: NONE }));
    await press("Back");
    expect(region("overlap").textContent).toBe("No overlap with other published ideas (compared with 12).");
    expect(screen.getByRole("button", { name: OVERLAP }).getAttribute("aria-disabled")).toBeNull();
    expect(fake.overlap).toHaveBeenCalledTimes(1);
  });


  it("keeps the answers when the owner comes back to step 1, without checking again", async () => {
    const fake = checksCalls({ disclosure: vi.fn(async () => ({ ok: true as const, value: BY_RULES })) });
    await check(OVERLAP, fake);
    await press(DISCLOSURE);
    await press("Continue");
    await settleLazy();
    expect(region("overlap")).toBeNull();
    await press("Back");
    expect(region("overlap").textContent).toBe("No overlap with other published ideas (compared with 12).");
    expect(region("disclosure").textContent).toContain("summary and the problem it solves");
    expect(fake.overlap).toHaveBeenCalledTimes(1);
    expect(fake.disclosure).toHaveBeenCalledTimes(1);
  });
});
