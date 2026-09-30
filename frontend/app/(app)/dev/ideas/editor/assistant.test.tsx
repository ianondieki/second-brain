import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  assistantCalls,
  CONSENT_OFF,
  CONSENT_ON,
  DEMO_FALLBACK,
  httpAssistant,
  PROPOSAL_ID,
  refusal,
  ROUTE,
  SERVER_MESSAGE,
  SUGGESTED,
  type FakeAnswer,
} from "@/test/assistant";
import { calls, READY, renderEditor } from "@/test/ideas-editor";

import type { AssistantSuggestion } from "../assistant";
import { EMPTY_STATE } from "../versions";
import { preloadAssistant } from "./Editor";

// REQ-PROP-05 (P13-F): the writing assistant's panel in the editor. The consent dialog shows the API's wording and
// sends its version back; nothing is sent before the owner turns the assistant on; a suggestion changes nothing until
// "Use this", which goes through the editor's own save; every refusal has its fixed sentence (never the API's);
// focus moves where the owner can carry on; the AI-drafted and demo-fallback labels (docs/spec/09).

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

beforeAll(async () => {
  // jsdom implements <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  await preloadAssistant(); // the panel's chunk, loaded before a render as the browser loads it on the first press
});

afterEach(() => {
  cleanup();
});

const OPEN = "Suggest a clearer teaser";
const dialog = () => screen.getByRole("dialog", { hidden: true }) as HTMLDialogElement;

async function open(fake: ReturnType<typeof assistantCalls> | ReturnType<typeof httpAssistant>["calls"]) {
  const editorCalls = calls();
  await renderEditor({ id: PROPOSAL_ID, initial: READY, assistant: fake });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: OPEN }));
  });
  return editorCalls;
}

async function press(name: string | RegExp) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

describe("closed", () => {
  it("is one secondary button that sends nothing until it is pressed", async () => {
    const fake = assistantCalls();
    await renderEditor({ id: PROPOSAL_ID, initial: READY, assistant: fake });
    const button = screen.getByRole("button", { name: OPEN });
    expect(button.hasAttribute("data-primary")).toBe(false);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1); // "Continue" stays the one primary action
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
    for (const call of Object.values(fake)) expect(call).not.toHaveBeenCalled();
  });
});

describe("the consent dialog", () => {
  it("shows the API's wording as it is, focuses 'Not now', and sends nothing before the owner turns it on", async () => {
    const fake = assistantCalls();
    await open(fake);
    expect(fake.consentState).toHaveBeenCalledWith(PROPOSAL_ID);
    const box = dialog();
    expect(box.open).toBe(true);
    expect(within(box).getByRole("heading", { name: "Turn on the writing assistant?" })).toBeTruthy();
    expect(box.querySelector("[data-consent-version]")?.textContent).toBe(CONSENT_OFF.text);
    expect(document.activeElement?.textContent).toBe("Not now");
    expect(fake.grantConsent).not.toHaveBeenCalled();
    expect(fake.suggest).not.toHaveBeenCalled();
  });

  it("sends back the version of the wording it showed, then asks once", async () => {
    const fake = assistantCalls();
    await open(fake);
    await press("Turn on and ask");
    expect(fake.grantConsent).toHaveBeenCalledTimes(1);
    expect(fake.grantConsent).toHaveBeenCalledWith(PROPOSAL_ID, CONSENT_OFF.version);
    expect(fake.suggest).toHaveBeenCalledTimes(1);
    expect(dialog().open).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Suggestion" }));
  });

  it("'Not now' closes the panel, sends nothing, and gives focus back to the button", async () => {
    const fake = assistantCalls();
    await open(fake);
    await press("Not now");
    expect(fake.grantConsent).not.toHaveBeenCalled();
    expect(fake.suggest).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { hidden: true })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: OPEN }));
  });

  it("Escape does the same as 'Not now'", async () => {
    const fake = assistantCalls();
    await open(fake);
    await act(async () => {
      dialog().close(); // what the browser does after the cancel event Escape fires
    });
    expect(fake.suggest).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: OPEN }));
  });

  it("shows the new wording when it changed, and sends the new version with the next press", async () => {
    const fake = assistantCalls({
      grantConsent: vi
        .fn()
        .mockResolvedValueOnce({ ok: false, problem: "consentTextChanged" })
        .mockResolvedValueOnce({ ok: true, value: { ...CONSENT_ON, version: "v2" } }),
      consentState: vi
        .fn()
        .mockResolvedValueOnce({ ok: true, value: CONSENT_OFF })
        .mockResolvedValueOnce({ ok: true, value: { ...CONSENT_OFF, text: "The new wording.", version: "v2" } }),
    });
    await open(fake);
    await press("Turn on and ask");
    expect(dialog().open).toBe(true);
    expect(within(dialog()).getByRole("alert").textContent).toBe("The wording has changed. Read it again, then choose.");
    expect(dialog().querySelector("[data-consent-version]")?.textContent).toBe("The new wording.");
    expect(fake.suggest).not.toHaveBeenCalled();
    await press("Turn on and ask");
    expect(fake.grantConsent).toHaveBeenLastCalledWith(PROPOSAL_ID, "v2");
    expect(fake.suggest).toHaveBeenCalledTimes(1);
  });

  it("is skipped while the assistant is already on for this sign-in", async () => {
    const fake = assistantCalls({ consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })) });
    await open(fake);
    expect(dialog().open).toBe(false);
    expect(fake.grantConsent).not.toHaveBeenCalled();
    expect(fake.suggest).toHaveBeenCalledTimes(1);
  });

  it("opens again when the API says the opt-in ended (403 consent_required)", async () => {
    const http = httpAssistant({
      [`GET ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_ON }, { status: 200, body: CONSENT_OFF }],
      [`POST ${ROUTE.suggestions}`]: [{ status: 403, body: refusal("consent_required") }],
    });
    await open(http.calls);
    await waitFor(() => expect(dialog().open).toBe(true));
    expect(within(dialog()).getByRole("alert").textContent).toBe(
      "The writing assistant is off for this sign-in. Turn it on to ask.",
    );
    expect(document.body.textContent).not.toContain(SERVER_MESSAGE);
  });

  it("over HTTP: GET the wording, POST its version, then POST for a suggestion", async () => {
    const http = httpAssistant({
      [`GET ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_OFF }],
      [`POST ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_ON }],
      [`POST ${ROUTE.suggestions}`]: [{ status: 200, body: SUGGESTED }],
    });
    await open(http.calls);
    await waitFor(() => expect(dialog().open).toBe(true));
    await press("Turn on and ask");
    await waitFor(() => expect(screen.getByText(SUGGESTED.teaser!.title)).toBeTruthy());
    expect(http.seen.map(({ method, path }) => `${method} ${path}`)).toEqual([
      `GET ${ROUTE.consent}`,
      `POST ${ROUTE.consent}`,
      `POST ${ROUTE.suggestions}`,
    ]);
    expect(JSON.parse(http.seen[1].body)).toEqual({ version: CONSENT_OFF.version });
  });
});

describe("a suggestion", () => {
  it("sits beside the current title and summary, labelled AI-drafted, with the placement hints", async () => {
    await open(assistantCalls({ consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })) }));
    const now = document.querySelector("[data-teaser='now']")!;
    const suggested = document.querySelector("[data-teaser='suggested']")!;
    expect(now.textContent).toContain(READY.title);
    expect(now.textContent).toContain(READY.summary);
    expect(suggested.textContent).toContain(SUGGESTED.teaser!.title);
    expect(suggested.textContent).toContain(SUGGESTED.teaser!.summary);
    const chips = [...document.querySelectorAll("#assistant-panel [data-chip]")].map((chip) => chip.textContent);
    expect(chips).toEqual(["AI-drafted"]);
    expect(screen.getByText("Pricing might belong in the public teaser.")).toBeTruthy();
    expect(screen.getByText(SUGGESTED.placement[0].reason)).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Suggestion" }));
  });

  it("changes nothing until 'Use this', then goes through the editor's own save", async () => {
    const editor = calls();
    const fake = assistantCalls({ consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })) });
    await renderEditor({ id: PROPOSAL_ID, initial: READY, assistant: fake, calls: editor });
    await press(OPEN);
    await waitFor(() => expect(screen.getByRole("button", { name: "Use this" })).toBeTruthy());
    // Shown, not applied: the fields keep the owner's text and nothing is saved, however long it stays on screen.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
    });
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(READY.title);
    expect((screen.getByLabelText("Summary") as HTMLTextAreaElement).value).toBe(READY.summary);
    expect(editor.saveState).not.toHaveBeenCalled();

    await press("Use this");
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe(SUGGESTED.teaser!.title);
    expect((screen.getByLabelText("Summary") as HTMLTextAreaElement).value).toBe(SUGGESTED.teaser!.summary);
    expect(document.activeElement?.textContent).toContain("The suggestion is now in your title and summary.");
    expect(screen.queryByRole("button", { name: "Use this" })).toBeNull();
    await waitFor(() => expect(editor.saveState).toHaveBeenCalledTimes(1), { timeout: 3000 });
    const [id, saved] = vi.mocked(editor.saveState).mock.calls[0];
    expect(id).toBe(PROPOSAL_ID);
    expect(saved.title).toBe(SUGGESTED.teaser!.title);
    expect(saved.summary).toBe(SUGGESTED.teaser!.summary);
    expect(fake.suggest).toHaveBeenCalledTimes(1); // applying never asks again
  });

  it("labels a demo fallback, offers nothing to use, and never shows the API's message", async () => {
    await open(
      assistantCalls({
        consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })),
        suggest: vi.fn(async () => ({ ok: true as const, value: DEMO_FALLBACK })),
      }),
    );
    const chips = [...document.querySelectorAll("#assistant-panel [data-chip]")].map((chip) => chip.textContent);
    expect(chips).toEqual(["Demo fallback"]);
    expect(screen.getByText("No model answered, so there is no suggestion. This is the demo fallback.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use this" })).toBeNull();
    expect(document.body.textContent).not.toContain(SERVER_MESSAGE);
  });

  it("shows placement hints alone when there is no new teaser", async () => {
    const hintsOnly: AssistantSuggestion = { ...SUGGESTED, teaser: null };
    await open(
      assistantCalls({
        consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })),
        suggest: vi.fn(async () => ({ ok: true as const, value: hintsOnly })),
      }),
    );
    expect(screen.getByText(/No new title or summary this time/)).toBeTruthy();
    expect(screen.getByText("Pricing might belong in the public teaser.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Use this" })).toBeNull();
  });
});

describe("before asking", () => {
  it("asks for a title or summary first, and sends nothing", async () => {
    const fake = assistantCalls();
    await renderEditor({ id: PROPOSAL_ID, initial: EMPTY_STATE, assistant: fake });
    await press(OPEN);
    expect(screen.getByRole("alert").textContent).toBe("Write a title or a summary first, then ask.");
    for (const call of Object.values(fake)) expect(call).not.toHaveBeenCalled();
  });

  it("saves what was typed first, and asks nothing when the save is refused", async () => {
    const fake = assistantCalls();
    const editor = calls({
      saveState: vi.fn(async () => ({
        outcome: { ok: false as const, problem: "fields" as const, fields: [{ field: "summary" as const, code: "contains_email" }] },
        held: [],
      })),
    });
    await renderEditor({ id: PROPOSAL_ID, initial: READY, assistant: fake, calls: editor });
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "Write to jane@example.com" } });
    await press(OPEN);
    await waitFor(() => expect(editor.saveState).toHaveBeenCalled());
    expect(await screen.findByText(/Your latest changes are not saved/)).toBeTruthy();
    for (const call of Object.values(fake)) expect(call).not.toHaveBeenCalled();
  });
});

describe("refusals", () => {
  const CASES: Array<[string, FakeAnswer, string]> = [
    ["429 assistant_busy", { status: 429, body: refusal("assistant_busy") }, "The writing assistant is still working on your last request. Try again in a moment."],
    ["429 assistant_rate_limited", { status: 429, body: refusal("assistant_rate_limited") }, "You have asked the writing assistant for many suggestions today. Try again tomorrow."],
    ["429 assistant_budget", { status: 429, body: refusal("assistant_budget") }, "You have used this month's writing assistant allowance."],
    ["503 assistant_paused", { status: 503, body: refusal("assistant_paused") }, "The writing assistant is paused for today. Try again tomorrow."],
    ["503 assistant_off", { status: 503, body: refusal("assistant_off") }, "The writing assistant is switched off for now."],
    ["403 assistant_demo_only", { status: 403, body: refusal("assistant_demo_only") }, "In this demo, the writing assistant works only with demo accounts."],
    ["403 tier2_disabled", { status: 403, body: refusal("tier2_disabled") }, "The writing assistant is not available on this server right now."],
    ["503 without a code", { status: 503, body: { detail: "Service Unavailable" } }, "The writing assistant could not answer just now. Try again later."],
    ["401", { status: 401, body: refusal("unauthenticated") }, "Your session has ended. Log in again, then come back to this idea."],
    ["404", { status: 404, body: refusal("not_found") }, "This idea is not one of yours, or it was deleted."],
    ["409 proposal_hidden", { status: 409, body: refusal("proposal_hidden") }, "This idea was deleted, so the assistant cannot read it."],
    ["a lost connection", "offline", "We could not reach the server. Check your connection, then try again."],
    ["500", { status: 500, body: refusal("internal") }, "Something went wrong. Try again in a moment."],
  ];

  it.each(CASES)("%s has its own fixed sentence", async (_, answer, sentence) => {
    const http = httpAssistant({
      [`GET ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_ON }],
      [`POST ${ROUTE.suggestions}`]: [answer],
    });
    await open(http.calls);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(sentence);
    expect(document.body.textContent).not.toContain(SERVER_MESSAGE);
    expect(screen.getByRole("button", { name: "Ask again" })).toBeTruthy();
  });

  const STATUSES: Array<[AssistantSuggestion["status"], string]> = [
    ["unavailable", "The writing assistant could not answer just now. Try again later."],
    // Also every reason the API keeps to itself, such as rejected:tier2_overlap (a suggestion copying confidential text).
    ["no_suggestion", "There is no suggestion to show for this teaser. Suggestions that copy wording from your full details are held back."],
    ["injection_suspected", "Part of your idea reads like instructions to the assistant, so it made no suggestion. Check the text, then ask again."],
  ];

  it.each(STATUSES)("status %s has its own fixed sentence", async (status, sentence) => {
    const body: AssistantSuggestion = { ...SUGGESTED, status, message: SERVER_MESSAGE, ai_drafted: false, teaser: null, placement: [] };
    const http = httpAssistant({
      [`GET ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_ON }],
      [`POST ${ROUTE.suggestions}`]: [{ status: 200, body }],
    });
    await open(http.calls);
    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(document.body.textContent).not.toContain(SERVER_MESSAGE);
    expect(document.querySelectorAll("#assistant-panel [data-chip]")).toHaveLength(0);
  });

  it("words a refused opt-in inside the dialog (403 tier2_disabled on POST consent)", async () => {
    const http = httpAssistant({
      [`GET ${ROUTE.consent}`]: [{ status: 200, body: CONSENT_OFF }],
      [`POST ${ROUTE.consent}`]: [{ status: 403, body: refusal("tier2_disabled") }],
    });
    await open(http.calls);
    await waitFor(() => expect(dialog().open).toBe(true));
    await press("Turn on and ask");
    await waitFor(() =>
      expect(within(dialog()).getByRole("alert").textContent).toBe(
        "The writing assistant is not available on this server right now.",
      ),
    );
  });
});

describe("turning it off", () => {
  it("sends DELETE, says so, moves focus to the notice, and asks for consent again next time", async () => {
    const fake = assistantCalls({
      consentState: vi
        .fn()
        .mockResolvedValueOnce({ ok: true, value: CONSENT_ON })
        .mockResolvedValueOnce({ ok: true, value: CONSENT_OFF }),
    });
    await open(fake);
    await press("Turn off the assistant for this sign-in");
    expect(fake.withdrawConsent).toHaveBeenCalledWith(PROPOSAL_ID);
    expect(document.activeElement?.textContent).toBe("The writing assistant is off for this sign-in.");
    expect(screen.queryByRole("button", { name: "Turn off the assistant for this sign-in" })).toBeNull();
    expect(document.querySelector("[data-teaser]")).toBeNull(); // its last answer goes with it
    expect(document.querySelectorAll("#assistant-panel [data-chip]")).toHaveLength(0);

    await press("Ask again");
    expect(fake.consentState).toHaveBeenCalledTimes(2);
    expect(dialog().open).toBe(true);
    expect(fake.suggest).toHaveBeenCalledTimes(1);
  });

  it("closes with 'Close', giving focus back to the button", async () => {
    await open(assistantCalls({ consentState: vi.fn(async () => ({ ok: true as const, value: CONSENT_ON })) }));
    await press("Close");
    expect(screen.queryByText("Suggestion")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: OPEN }));
  });
});
