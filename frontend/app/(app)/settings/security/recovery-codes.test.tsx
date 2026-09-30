import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { RecoveryCodeList } from "./RecoveryCodeList";
import { SecuritySettings } from "./SecuritySettings";

// REQ-AUTH-01 follow-up 8, frontend half: "Get new recovery codes" on the "on" screen (POST
// /api/auth/totp/recovery-codes with the current password when the account has one; a stale second factor asks for a
// code first), the codes shown once, and every refusal as a fixed message, never the API's own words.

const mocks = vi.hoisted(() => ({ post: vi.fn(), del: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  api: {
    POST: (...args: unknown[]) => mocks.post(...args),
    DELETE: (...args: unknown[]) => mocks.del(...args),
    GET: () => Promise.reject(new Error("no GET expected")),
  },
}));

const SERVER_TEXT = "server text that must never be shown";

function answer(status: number, code?: string) {
  const error = code ? { detail: { code, message: SERVER_TEXT } } : undefined;
  return { data: undefined, error, response: new Response(error ? JSON.stringify(error) : null, { status }) };
}

function ok(data: unknown) {
  return { data, error: undefined, response: new Response(JSON.stringify(data), { status: 200 }) };
}

const CODES = Array.from({ length: 10 }, (_, i) => `k7mq-x2p${i}`);
const NEW_CODES = ok({ recovery_codes: CODES });
const RENEW = "/api/auth/totp/recovery-codes";
const PASSWORD_FIELD = "Confirm with your current password";
const READY = "Your new recovery codes are ready. Your old codes no longer work.";

/** Answers POSTs in order per path (the last answer repeats); other paths get 204. */
function answers(byPath: Record<string, unknown[]>) {
  const seen: Record<string, number> = {};
  mocks.post.mockImplementation((path: string) => {
    const list = byPath[path];
    if (!list) return Promise.resolve(answer(204));
    const index = Math.min(seen[path] ?? 0, list.length - 1);
    seen[path] = (seen[path] ?? 0) + 1;
    const result = list[index];
    return result instanceof Error ? Promise.reject(result) : Promise.resolve(result);
  });
}

function onScreen({ passwordSet = true, required = true }: { passwordSet?: boolean; required?: boolean } = {}) {
  const ui: ReactNode = (
    <>
      <SecuritySettings enrolled required={required} homeHref="/org" email="a@example.com" productName="Bridge" />
      <PasswordSettings email="a@example.com" />
    </>
  );
  return renderWithIntl(<PasswordStateProvider initial={passwordSet}>{ui}</PasswordStateProvider>);
}

/**
 * Whether any React component above `node` keeps `value` in its state (the hooks' memoizedState chain). The form
 * that took the password unmounts only when "I have saved my codes" is pressed, so this is how a test sees that the
 * password is not held while the codes are on screen. Reads React's fiber, a test-only dependency on its internals.
 */
function stateHolds(node: Element, value: string): boolean {
  const key = Object.keys(node).find((k) => k.startsWith("__reactFiber$"));
  type Fiber = { return: Fiber | null; memoizedState: unknown };
  type Hook = { memoizedState: unknown; next: Hook | null };
  let fiber = key ? ((node as unknown as Record<string, Fiber>)[key] ?? null) : null;
  expect(fiber, "a React fiber on the node").not.toBeNull();
  for (; fiber; fiber = fiber.return) {
    let hook = fiber.memoizedState as Hook | null;
    for (let n = 0; hook && typeof hook === "object" && "next" in hook && n < 100; n++, hook = hook.next) {
      if (hook.memoizedState === value) return true;
    }
  }
  return false;
}

const opener = () => screen.getByRole("button", { name: "Get new recovery codes" });
const passwordSection = () => screen.queryByRole("region", { name: "Password" });
const renewCalls = () => mocks.post.mock.calls.filter(([path]) => path === RENEW);

/** Opens the form and waits for it (it loads on demand). */
async function open() {
  fireEvent.click(opener());
  return screen.findByText("Your old recovery codes stop working as soon as the new ones are made.");
}

async function submitWith(password?: string) {
  await open();
  if (password !== undefined) {
    fireEvent.change(screen.getByLabelText(PASSWORD_FIELD, { selector: "input" }), { target: { value: password } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Get new recovery codes" }));
}

beforeEach(() => {
  mocks.post.mockReset();
  mocks.del.mockReset();
  mocks.push.mockReset();
  // Focus after an API answer must not wait for an animation frame (reveal.ts): here frames never come.
  vi.stubGlobal("requestAnimationFrame", () => 0);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the 'on' screen", () => {
  it("offers new recovery codes under their own heading, as a secondary action", () => {
    const { container } = onScreen();
    expect(screen.getByRole("region", { name: "Recovery codes" })).toBeTruthy();
    expect(opener().hasAttribute("data-primary")).toBe(false);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("makes it the one primary action when setup's answer with the codes was lost", async () => {
    answers({
      "/api/auth/totp/enrol": [ok({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x?issuer=Bridge" })],
      "/api/auth/totp/confirm": [new TypeError("Failed to fetch")],
    });
    mocks.del.mockResolvedValue(answer(409, "totp_already_enabled"));
    const { container } = renderWithIntl(
      <PasswordStateProvider initial={false}>
        <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" productName="Bridge" />
      </PasswordStateProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    fireEvent.change(await screen.findByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByText("We could not reach the server. Check your connection, then try again.");
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));

    await screen.findByText("Two-step sign-in is on.");
    expect(screen.getByRole("alert").textContent).toMatch(/Then get new recovery codes below\.$/);
    expect(opener().hasAttribute("data-primary")).toBe(true);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);

    // Getting them settles the notice.
    answers({ [RENEW]: [NEW_CODES] });
    fireEvent.click(opener());
    fireEvent.click(await screen.findByRole("button", { name: "Get new recovery codes" }));
    await screen.findByText(READY);
    expect(screen.queryByText(/could not be shown/)).toBeNull();
  });
});

describe("getting new recovery codes with a password on file", () => {
  it("asks for the password first, with focus on it, and one task on screen", async () => {
    const { container } = onScreen({ required: false });
    await open();
    const field = screen.getByLabelText(PASSWORD_FIELD, { selector: "input" });
    await waitFor(() => expect(document.activeElement).toBe(field));
    expect(field.closest("form")!.querySelector<HTMLInputElement>('input[autocomplete="username"]')?.value).toBe(
      "a@example.com",
    );
    // Turning off and the Password section step aside; the submit is the one primary action and names the warning.
    expect(screen.queryByRole("button", { name: "Turn off two-step sign-in" })).toBeNull();
    expect(passwordSection()).toBeNull();
    const submit = screen.getByRole("button", { name: "Get new recovery codes" });
    expect(submit.hasAttribute("data-primary")).toBe(true);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(document.getElementById(submit.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Your old recovery codes stop working as soon as the new ones are made.",
    );
  });

  it("says the password is needed without asking the server when the field is empty", async () => {
    onScreen();
    await submitWith();
    expect(await screen.findByText("Enter your current password to make this change.")).toBeTruthy();
    expect(renewCalls()).toHaveLength(0);
  });

  it("sends the password and shows the ten codes once, with copy, download and the 'replaced' notice", async () => {
    answers({ [RENEW]: [NEW_CODES] });
    const { container } = onScreen();
    await submitWith("jacaranda");
    const ready = await screen.findByText(READY);
    expect(renewCalls()).toEqual([[RENEW, { body: { current_password: "jacaranda" }, signal: expect.any(AbortSignal) }]]);
    expect(document.activeElement).toBe(ready.closest('[role="status"]'));
    // The password is dropped once the codes are made: not in the page, and not kept in the form's state.
    for (const input of document.querySelectorAll("input")) expect(input.value).not.toBe("jacaranda");
    expect(stateHolds(ready, "jacaranda")).toBe(false);
    const list = screen.getByTestId("recovery-codes");
    expect([...list.querySelectorAll("li")].map((li) => li.textContent)).toEqual(CODES);
    expect(screen.getByRole("button", { name: "Copy codes" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download codes" })).toBeTruthy();
    expect(screen.getByText(/we will not show them again/)).toBeTruthy();
    expect(screen.queryByLabelText(PASSWORD_FIELD, { selector: "input" })).toBeNull();
    const done = screen.getByRole("button", { name: "I have saved my codes" });
    expect(done.hasAttribute("data-primary")).toBe(true);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);

    // Done: the codes leave the page, and focus goes back to where it began.
    fireEvent.click(done);
    expect(screen.queryByTestId("recovery-codes")).toBeNull();
    expect(document.activeElement).toBe(opener());
    expect(passwordSection()).not.toBeNull();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("asks for a fresh authenticator code when the second factor is stale, then sends the same password again", async () => {
    answers({ [RENEW]: [answer(403, "step_up_required"), NEW_CODES], "/api/auth/step-up": [answer(204)] });
    onScreen();
    await submitWith("jacaranda");
    expect(await screen.findByText("To get new codes, enter the current code from your authenticator app.")).toBeTruthy();
    const code = screen.getByLabelText("Code from your app");
    await waitFor(() => expect(document.activeElement).toBe(code));
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and get new codes" }));

    await screen.findByText(READY);
    const sent = { body: { current_password: "jacaranda" }, signal: expect.any(AbortSignal) };
    expect(mocks.post.mock.calls).toEqual([[RENEW, sent], ["/api/auth/step-up", { body: { code: "123456" } }], [RENEW, sent]]);
  });

  it("can be cancelled at the code step, back to the button, with nothing replaced", async () => {
    answers({ [RENEW]: [answer(403, "step_up_required")] });
    onScreen();
    await submitWith("jacaranda");
    await screen.findByText("To get new codes, enter the current code from your authenticator app.");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(opener());
    expect(renewCalls()).toHaveLength(1);
  });

  it("asks for the password again when it was wrong, the field emptied and focused", async () => {
    answers({ [RENEW]: [answer(403, "current_password_required")] });
    onScreen();
    await submitWith("not it");
    const message = await screen.findByText("Enter your current password to make this change.");
    const field = screen.getByLabelText<HTMLInputElement>(PASSWORD_FIELD, { selector: "input" });
    expect(field.value).toBe("");
    expect(document.activeElement).toBe(field);
    expect(message).toBeTruthy();
    expect(document.body.textContent).not.toContain(SERVER_TEXT);
  });

  it("goes back to the start with a fixed message when two-step sign-in was turned off meanwhile", async () => {
    answers({ [RENEW]: [answer(409, "totp_not_enabled")] });
    onScreen();
    await submitWith("jacaranda");
    const error = await screen.findByText("Two-step sign-in is off, so there are no recovery codes to replace.");
    expect(document.activeElement).toBe(error.closest('[role="alert"]'));
    expect(screen.getByRole("button", { name: "Turn on two-step sign-in" })).toBeTruthy();
    expect(screen.queryByText("Two-step sign-in is on.")).toBeNull();
    expect(passwordSection()).not.toBeNull();
  });

  const UNKNOWN =
    "We could not tell whether new codes were made. If they were, your old codes no longer work: get new recovery " +
    "codes again.";

  it.each([
    ["no connection", () => new TypeError("Failed to fetch")],
    ["500", () => answer(500)],
    ["504 proxy timeout", () => answer(504)],
    ["a code this page does not know", () => answer(409, "a_code_this_page_does_not_know")],
    ["a success without codes", () => ok({ recovery_codes: [] })],
  ])("says the old codes may no longer work when the answer is lost or unreadable (%s)", async (_, lost) => {
    answers({ [RENEW]: [lost()] });
    onScreen();
    await submitWith("jacaranda");
    const notice = await screen.findByText(UNKNOWN);
    expect(document.activeElement).toBe(notice.closest('[role="alert"]'));
    expect(document.body.textContent).not.toContain(SERVER_TEXT);
    expect(screen.queryByText("Something went wrong. Try again in a moment.")).toBeNull();
    // The form stays, the password kept, so getting codes again is one press.
    expect(screen.getByLabelText<HTMLInputElement>(PASSWORD_FIELD, { selector: "input" }).value).toBe("jacaranda");
  });

  it("gives up after 10 s without an answer and says the old codes may no longer work", async () => {
    const timeouts: Array<{ ms: number; controller: AbortController }> = [];
    const timeout = vi.spyOn(AbortSignal, "timeout").mockImplementation((ms) => {
      const controller = new AbortController();
      timeouts.push({ ms, controller });
      return controller.signal;
    });
    try {
      mocks.post.mockImplementation(
        (_path: string, init?: { signal?: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
          }),
      );
      onScreen();
      await submitWith("jacaranda");
      await screen.findByRole("button", { name: "Getting codes…" });
      expect(timeouts.map(({ ms }) => ms)).toEqual([10_000]);
      expect(mocks.post.mock.calls[0][1]?.signal).toBe(timeouts[0].controller.signal);
      timeouts[0].controller.abort(new DOMException("signal timed out", "TimeoutError"));
      expect(await screen.findByText(UNKNOWN)).toBeTruthy();
      expect(screen.getByRole("button", { name: "Get new recovery codes" }).getAttribute("aria-disabled")).toBeNull();
    } finally {
      timeout.mockRestore();
    }
  });

  it.each([
    [answer(429, "too_many_attempts"), "Too many attempts. Wait a minute, then try again."],
    [answer(403, "csrf_failed"), "Your session changed. Reload the page, then try again."],
  ])("keeps the form with a fixed message for other refusals (%#)", async (refusal, message) => {
    answers({ [RENEW]: [refusal] });
    onScreen();
    await submitWith("jacaranda");
    const error = await screen.findByText(message);
    expect(document.activeElement).toBe(error.closest('[role="alert"]'));
    expect(document.body.textContent).not.toContain(SERVER_TEXT);
    // The password stays, so sending again is one press.
    expect(screen.getByLabelText<HTMLInputElement>(PASSWORD_FIELD, { selector: "input" }).value).toBe("jacaranda");
    expect(screen.queryByTestId("recovery-codes")).toBeNull();
  });

  it("links to the login page when the session has ended", async () => {
    answers({ [RENEW]: [answer(401, "unauthenticated")] });
    onScreen();
    await submitWith("jacaranda");
    expect((await screen.findByRole("link", { name: "Log in again" })).getAttribute("href")).toBe("/login");
  });

  it("comes back to the form, password kept, when the retry after the code step is refused", async () => {
    answers({
      [RENEW]: [answer(403, "step_up_required"), answer(429, "too_many_attempts")],
      "/api/auth/step-up": [answer(204)],
    });
    onScreen();
    await submitWith("jacaranda");
    fireEvent.change(await screen.findByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and get new codes" }));
    await screen.findByText("Too many attempts. Wait a minute, then try again.");
    expect(screen.queryByLabelText("Code from your app")).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>(PASSWORD_FIELD, { selector: "input" }).value).toBe("jacaranda");
  });

  it("sends once however often the button is pressed while it works", async () => {
    mocks.post.mockReturnValue(new Promise(() => {}));
    onScreen();
    await submitWith("jacaranda");
    const busy = await screen.findByRole("button", { name: "Getting codes…" });
    fireEvent.click(busy);
    fireEvent.click(busy);
    expect(renewCalls()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Cancel" }).getAttribute("aria-disabled")).toBe("true");
  });
});

describe("getting new recovery codes without a password on file", () => {
  it("asks for no password and sends none; focus starts on the button", async () => {
    answers({ [RENEW]: [NEW_CODES] });
    onScreen({ passwordSet: false });
    await open();
    expect(screen.queryByLabelText(PASSWORD_FIELD, { selector: "input" })).toBeNull();
    const submit = screen.getByRole("button", { name: "Get new recovery codes" });
    await waitFor(() => expect(document.activeElement).toBe(submit));
    fireEvent.click(submit);
    await screen.findByText(READY);
    expect(renewCalls()).toEqual([[RENEW, { body: { current_password: null }, signal: expect.any(AbortSignal) }]]);
  });

  it("shows the password field once the API asks for one", async () => {
    answers({ [RENEW]: [answer(403, "current_password_required")] });
    onScreen({ passwordSet: false });
    await submitWith();
    const field = await screen.findByLabelText(PASSWORD_FIELD, { selector: "input" });
    expect(screen.getByText("Enter your current password to make this change.")).toBeTruthy();
    expect(document.activeElement).toBe(field);
  });
});

describe("RecoveryCodeList", () => {
  const CLEARED =
    "Your recovery codes are no longer shown on this page. If you did not save them, get new recovery codes.";

  it.each([
    ["pagehide (the page is about to enter the back-forward cache)", () => new PageTransitionEvent("pagehide", { persisted: true })],
    ["pagehide (the page unloads)", () => new PageTransitionEvent("pagehide", { persisted: false })],
    ["pageshow from the back-forward cache", () => new PageTransitionEvent("pageshow", { persisted: true })],
  ])("removes the codes from the page on %s", (_, event) => {
    const { container } = renderWithIntl(<RecoveryCodeList codes={CODES} />);
    window.dispatchEvent(event());
    // At once (flushSync), since a page is frozen for the cache right after its pagehide handlers.
    expect(screen.queryByTestId("recovery-codes")).toBeNull();
    for (const code of CODES) expect(container.textContent).not.toContain(code);
    expect(screen.getByText(CLEARED)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copy codes" })).toBeNull();
  });

  it("keeps the codes on a first pageshow (not from the cache)", () => {
    renderWithIntl(<RecoveryCodeList codes={CODES} />);
    window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    expect(screen.getByTestId("recovery-codes")).toBeTruthy();
  });

  it("clears the codes at the end of setup too", async () => {
    mocks.post.mockImplementation((path: string) =>
      Promise.resolve(
        path === "/api/auth/totp/confirm"
          ? NEW_CODES
          : ok({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x?issuer=Bridge" }),
      ),
    );
    renderWithIntl(
      <PasswordStateProvider initial={false}>
        <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" productName="Bridge" />
      </PasswordStateProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    fireEvent.change(await screen.findByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByTestId("recovery-codes");
    window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));
    expect(screen.queryByTestId("recovery-codes")).toBeNull();
    expect(screen.getByText(CLEARED)).toBeTruthy();
  });

  it("copies the codes one per line", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderWithIntl(<RecoveryCodeList codes={CODES} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy codes" }));
    expect(await screen.findByText("Codes copied.")).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith(CODES.join("\n"));
  });

  it("says to copy by hand when the clipboard refuses", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error("no")) } });
    renderWithIntl(<RecoveryCodeList codes={CODES} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy codes" }));
    expect(await screen.findByText("Copying did not work. Select the text and copy it instead.")).toBeTruthy();
  });

  it("downloads the codes as a text file, one per line", async () => {
    const blobs: Blob[] = [];
    const create = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:codes";
    });
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      renderWithIntl(<RecoveryCodeList codes={CODES} />);
      fireEvent.click(screen.getByRole("button", { name: "Download codes" }));
      expect(click).toHaveBeenCalledTimes(1);
      expect(await blobs[0].text()).toBe(`${CODES.join("\n")}\n`);
      expect(revoke).toHaveBeenCalledWith("blob:codes");
    } finally {
      click.mockRestore();
    }
  });
});
