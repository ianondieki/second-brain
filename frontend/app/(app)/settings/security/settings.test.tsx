import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/schema";
import { renderWithIntl } from "@/test/intl";

import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { issuerOf, SecuritySettings } from "./SecuritySettings";
import { StepUpForm } from "./StepUpForm";

const mocks = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({
  api: { POST: (...args: unknown[]) => mocks.post(...args), GET: (...args: unknown[]) => mocks.get(...args) },
}));

function answer(status: number, code?: string) {
  const body = code ? JSON.stringify({ detail: { code, message: "server text" } }) : null;
  const error = code ? { detail: { code, message: "server text" } } : undefined;
  return { data: undefined, error, response: new Response(body, { status }) };
}

function ok(data: unknown) {
  return { data, error: undefined, response: new Response(JSON.stringify(data), { status: 200 }) };
}

const ENROLMENT = {
  secret: "JBSWY3DPEHPK3PXPJBSWY3DP",
  otpauth_uri: "otpauth://totp/Bridge:a%40example.com?secret=JBSWY3DPEHPK3PXPJBSWY3DP&issuer=Bridge",
};
const RECOVERY_CODES = Array.from({ length: 10 }, (_, i) => `code-${i}`);

/** GET /api/auth/me for a signed-in org owner, with two-step sign-in on or off on the server. */
function me(enrolled: boolean): components["schemas"]["MeResponse"] {
  return {
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      email: "a@example.com",
      display_name: "Amani",
      email_verified: true,
      locale: "en",
      password_set: true,
      staff_role: null,
      totp_enabled: enrolled,
    },
    memberships: [],
    mfa: { enrolled, required: true, verified: enrolled },
    side: "org",
  };
}

/**
 * Answers each API path with the given result (a promise that never settles keeps the call pending, an Error makes
 * it throw as fetch does offline); POSTs to other paths with 204. An unlisted GET fails, so no test depends on a
 * status check it did not set up.
 */
function answerWith(answers: Record<string, unknown>) {
  const reply = (path: string, otherwise: unknown) => {
    const result = answers[path] ?? otherwise;
    return result instanceof Error ? Promise.reject(result) : result;
  };
  mocks.post.mockImplementation((path: string) => reply(path, answer(204)));
  mocks.get.mockImplementation((path: string) => reply(path, answer(500)));
}

function page(passwordSet: boolean, children: ReactNode) {
  return renderWithIntl(<PasswordStateProvider initial={passwordSet}>{children}</PasswordStateProvider>);
}

/** The `autocomplete="username"` fields in the form that holds this password field. */
function usernameFields(passwordField: HTMLElement) {
  return [...passwordField.closest("form")!.querySelectorAll<HTMLInputElement>('input[autocomplete="username"]')];
}

/** The notice (role alert or status) whose words are exactly `text`. */
function noticeReading(text: string) {
  return screen.getByText(text).closest<HTMLElement>('[role="alert"], [role="status"]');
}

/** Where Tab goes from `from`: the next focusable element in document order (these pages set no tabindex > 0). */
function nextInTabOrder(from: Element) {
  const focusable = document.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]");
  return [...focusable].find(
    (element) =>
      Boolean(from.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      element.tabIndex >= 0 &&
      !element.closest("[hidden]") &&
      !element.matches(":disabled"),
  );
}

const ENROL_FIELD = "Confirm with your current password";
const CANCELLED = "Setup cancelled. If you added Bridge to your authenticator app, delete that entry.";
const twoStep = (
  <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" productName="Bridge" />
);

/** Starts setup with the password on file and waits for the key (the page must ask for the password). */
async function startSetup() {
  fireEvent.change(screen.getByLabelText(ENROL_FIELD, { selector: "input" }), { target: { value: "jacaranda" } });
  fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
  await screen.findByTestId("totp-key");
}

beforeEach(() => {
  mocks.post.mockReset();
  mocks.get.mockReset();
  mocks.push.mockReset();
});
afterEach(cleanup);

describe("PasswordSettings", () => {
  it("asks for the current password only when the account has one", () => {
    page(true, <PasswordSettings email="a@example.com" />);
    expect(screen.getByLabelText("Current password", { selector: "input" })).toBeTruthy();
    cleanup();
    page(false, <PasswordSettings email="a@example.com" />);
    expect(screen.queryByLabelText("Current password", { selector: "input" })).toBeNull();
    expect(screen.getByLabelText("New password", { selector: "input" })).toBeTruthy();
  });

  it("names the account for password managers with a hidden username field", () => {
    page(true, <PasswordSettings email="a@example.com" />);
    const usernames = usernameFields(screen.getByLabelText("New password", { selector: "input" }));
    expect(usernames).toHaveLength(1);
    expect(usernames[0].value).toBe("a@example.com");
    expect(usernames[0].hidden).toBe(true); // never focused or announced
  });

  it("links to the login page when the session has ended", async () => {
    mocks.post.mockResolvedValue(answer(401, "unauthenticated"));
    page(false, <PasswordSettings email="a@example.com" />);
    fireEvent.change(screen.getByLabelText("New password", { selector: "input" }), {
      target: { value: "a long enough password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect((await screen.findByRole("link", { name: "Log in again" })).getAttribute("href")).toBe("/login");
  });
});

describe("two-step setup with a password on file", () => {
  it("names the account beside the password field, so a password manager fills the right one", () => {
    page(true, twoStep);
    const usernames = usernameFields(screen.getByLabelText(ENROL_FIELD, { selector: "input" }));
    expect(usernames).toHaveLength(1);
    expect(usernames[0].value).toBe("a@example.com");
    expect(usernames[0].hidden).toBe(true);
  });

  it("has no username field while it asks for no password", () => {
    page(false, twoStep);
    expect(document.querySelector('input[autocomplete="username"]')).toBeNull();
  });
});

describe("two-step setup without a password on file (password_set false)", () => {
  it("keeps the password field once the API asks for it, while the person types", async () => {
    mocks.post.mockResolvedValue(answer(403, "current_password_required"));
    page(false, twoStep);
    expect(screen.queryByLabelText(ENROL_FIELD, { selector: "input" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    const field = await screen.findByLabelText(ENROL_FIELD, { selector: "input" });
    fireEvent.change(field, { target: { value: "j" } });
    fireEvent.change(field, { target: { value: "jacaranda" } });
    expect(screen.getByLabelText(ENROL_FIELD, { selector: "input" })).toBeTruthy();

    // And it is still there on the next attempt, sent with the request.
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1]).toEqual(["/api/auth/totp/enrol", { body: { password: "jacaranda" } }]);
    expect(screen.getByLabelText(ENROL_FIELD, { selector: "input" })).toBeTruthy();
  });

  it("asks for the password straight away once one is saved in the Password section", async () => {
    mocks.post.mockResolvedValue(answer(204));
    page(
      false,
      <>
        {twoStep}
        <PasswordSettings email="a@example.com" />
      </>,
    );
    expect(screen.queryByLabelText(ENROL_FIELD, { selector: "input" })).toBeNull();
    fireEvent.change(screen.getByLabelText("New password", { selector: "input" }), {
      target: { value: "a long enough password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect(await screen.findByLabelText(ENROL_FIELD, { selector: "input" })).toBeTruthy();
  });
});

describe("the Password section during two-step setup", () => {
  const passwordSection = () => screen.queryByRole("region", { name: "Password" });

  function securityPage() {
    page(
      true,
      <>
        {twoStep}
        <PasswordSettings email="a@example.com" />
      </>,
    );
  }

  it("steps aside while the setup steps are shown and comes back, as typed, when setup is cancelled", async () => {
    answerWith({ "/api/auth/totp/enrol": ok(ENROLMENT) });
    securityPage();
    expect(passwordSection()).not.toBeNull();
    fireEvent.change(screen.getByLabelText("New password", { selector: "input" }), {
      target: { value: "typed before setup" },
    });

    await startSetup();
    expect(passwordSection()).toBeNull();
    expect(document.getElementById("password")!.hidden).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    expect(passwordSection()).not.toBeNull();
    expect(screen.queryByTestId("totp-key")).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>("New password", { selector: "input" }).value).toBe(
      "typed before setup",
    );
    // Focus goes to the notice that says what happened (above the steps, so off screen at 360 px without it), not to
    // the top of the page; the next Tab reaches where setup starts again (the password it asks for).
    const notice = noticeReading(CANCELLED);
    await waitFor(() => expect(document.activeElement).toBe(notice));
    expect(nextInTabOrder(notice!)).toBe(screen.getByLabelText(ENROL_FIELD, { selector: "input" }));
  });

  it("says setup was cancelled and what to tidy up, with still one primary action", async () => {
    answerWith({ "/api/auth/totp/enrol": ok(ENROLMENT) });
    const { container } = page(true, twoStep);
    await startSetup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    expect(screen.getByRole("status").textContent).toBe(CANCELLED);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);

    // Starting again clears it.
    await startSetup();
    expect(screen.queryByText(CANCELLED)).toBeNull();
  });

  it("names the entry to delete as the authenticator app lists it: the setup key's issuer", async () => {
    // After a rename (G5), the API's product name reaches the setup key before any copy changes.
    const renamed = { ...ENROLMENT, otpauth_uri: ENROLMENT.otpauth_uri.replaceAll("Bridge", "Kiungo") };
    answerWith({ "/api/auth/totp/enrol": ok(renamed) });
    page(true, twoStep);
    await startSetup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    expect(screen.getByRole("status").textContent).toBe(
      "Setup cancelled. If you added Kiungo to your authenticator app, delete that entry.",
    );
  });

  it("falls back to the product name when the setup key names no issuer", async () => {
    const unnamed = { ...ENROLMENT, otpauth_uri: "otpauth://totp/a%40example.com?secret=JBSWY3DPEHPK3PXPJBSWY3DP" };
    answerWith({ "/api/auth/totp/enrol": ok(unnamed) });
    page(true, <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" productName="Daraja" />);
    await startSetup();
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    expect(screen.getByRole("status").textContent).toBe(
      "Setup cancelled. If you added Daraja to your authenticator app, delete that entry.",
    );
  });

  it("puts focus on the notice, one Tab before the start button, after cancelling without a password", async () => {
    answerWith({ "/api/auth/totp/enrol": ok(ENROLMENT) });
    page(false, twoStep);
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    await screen.findByTestId("totp-key");
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    const notice = noticeReading(CANCELLED);
    await waitFor(() => expect(document.activeElement).toBe(notice));
    expect(nextInTabOrder(notice!)).toBe(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
  });

  it("stays hidden through the recovery codes, which cannot be cancelled; Done ends setup", async () => {
    answerWith({
      "/api/auth/totp/enrol": ok(ENROLMENT),
      "/api/auth/totp/confirm": ok({ recovery_codes: RECOVERY_CODES }),
    });
    securityPage();
    await startSetup();

    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByTestId("recovery-codes");
    expect(passwordSection()).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel setup" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "I have saved my codes" }));
    expect(mocks.push).toHaveBeenCalledWith("/org");
  });

  it("replaces the setup steps with a new list for the recovery codes, focus on its current step", async () => {
    answerWith({
      "/api/auth/totp/enrol": ok(ENROLMENT),
      "/api/auth/totp/confirm": ok({ recovery_codes: RECOVERY_CODES }),
    });
    securityPage();
    await startSetup();
    const setupList = screen.getByRole("list", { name: "Setup steps" });

    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByTestId("recovery-codes");

    // A new stage, not the old list with step 3 sliding up into the space steps 1-2 leave (a layout shift at 360 px).
    const codesList = screen.getByRole("list", { name: "Setup steps" });
    expect(codesList).not.toBe(setupList);
    expect(setupList.isConnected).toBe(false);
    const current = codesList.querySelector<HTMLElement>(":scope > li[aria-current='step'] h3");
    expect(current?.textContent).toBe("Save your recovery codes");
    await waitFor(() => expect(document.activeElement).toBe(current));
  });

  it("comes back when the server has lost the pending setup and it starts again", async () => {
    answerWith({
      "/api/auth/totp/enrol": ok(ENROLMENT),
      "/api/auth/totp/confirm": answer(409, "no_pending_enrolment"),
      "/api/auth/me": ok(me(false)), // and two-step sign-in is not on (see the lost-answer tests below)
    });
    securityPage();
    await startSetup();

    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByRole("button", { name: "Turn on two-step sign-in" });
    expect(passwordSection()).not.toBeNull();
    const error = screen.getByRole("alert"); // the error says why; no "cancelled" line
    expect(error.textContent).toBe("Start the setup again to get a new key.");
    expect(screen.queryByText(CANCELLED)).toBeNull();
    // Focus is not left on the page body: it goes to the error (above the steps), and the next Tab to where setup
    // starts again.
    await waitFor(() => expect(document.activeElement).toBe(error));
    expect(nextInTabOrder(error)).toBe(screen.getByLabelText(ENROL_FIELD, { selector: "input" }));
  });

  it("ignores Cancel while a code is being checked, so a confirmed setup is never hidden", async () => {
    answerWith({ "/api/auth/totp/enrol": ok(ENROLMENT), "/api/auth/totp/confirm": new Promise(() => {}) });
    securityPage();
    await startSetup();

    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    const cancel = screen.getByRole("button", { name: "Cancel setup" });
    await waitFor(() => expect(cancel.getAttribute("aria-disabled")).toBe("true"));
    fireEvent.click(cancel);
    expect(screen.getByTestId("totp-key")).toBeTruthy();
    expect(passwordSection()).toBeNull();
  });
});

describe("a confirmation whose answer never arrived (the server may have turned two-step sign-in on)", () => {
  // Past the code check, the server commits in one go: two-step sign-in on, recovery codes made, the "turned on"
  // email queued. A lost answer (offline, a reset connection), a 5xx or a proxy timeout can come after that commit.
  // "Delete that entry" would then leave the person without a second factor or recovery codes: locked out at the
  // next sign-in. So before cancelling, the page asks GET /api/auth/me.
  const NOT_SHOWN = "Your recovery codes could not be shown. Keep the Bridge entry in your authenticator app: you need its codes to log in.";
  const NOT_SHOWN_TURN_OFF =
    "Your recovery codes could not be shown. Keep the Bridge entry in your authenticator app: you need its codes " +
    "to log in. To get recovery codes, turn two-step sign-in off, then set it up again.";
  const UNKNOWN =
    "We could not check whether two-step sign-in is on. Reload this page to see, and until then keep the Bridge " +
    "entry in your authenticator app.";
  const LOST: Array<[string, () => unknown]> = [
    ["no connection", () => new TypeError("Failed to fetch")],
    ["500", () => answer(500)],
    ["502 from the proxy", () => answer(502)],
    ["504 proxy timeout", () => answer(504)],
  ];
  const cancelButton = () => screen.getByRole("button", { name: "Cancel setup" });
  const confirmButton = () => screen.getByRole("button", { name: "Confirm code" });

  /** Setup started, a code sent, and the confirmation settled (the button reads "Confirm code" again, not busy). */
  async function confirmFails(confirm: unknown, meAnswer?: unknown, ui = twoStep) {
    answerWith({
      "/api/auth/totp/enrol": ok(ENROLMENT),
      "/api/auth/totp/confirm": confirm,
      ...(meAnswer === undefined ? {} : { "/api/auth/me": meAnswer }),
    });
    const view = page(true, ui);
    await startSetup();
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(confirmButton());
    expect(mocks.post).toHaveBeenLastCalledWith("/api/auth/totp/confirm", { body: { code: "123456" } });
    await waitFor(() => expect(confirmButton().getAttribute("aria-disabled")).toBeNull());
    return view;
  }

  it.each(LOST)("turns to 'on' with no delete advice when Cancel finds it on (%s)", async (_, failure) => {
    const { container } = await confirmFails(failure(), ok(me(true)));
    fireEvent.click(cancelButton());

    expect(await screen.findByText("Two-step sign-in is on.")).toBeTruthy();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(mocks.get.mock.calls[0][0]).toBe("/api/auth/me");
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toBe(NOT_SHOWN); // the role keeps it on: no advice to turn it off
    expect(container.textContent).not.toMatch(/delete|cancelled/i);
    expect(screen.queryByTestId("totp-key")).toBeNull();
    expect(container.querySelectorAll("[data-primary]").length).toBeLessThanOrEqual(1);
    // Focus moves to the notice, not the page body, so a screen reader reads it.
    await waitFor(() => expect(document.activeElement).toBe(notice));
  });

  it("points to new recovery codes (turn off, set up again) when the role lets the person turn it off", async () => {
    const optional = (
      <SecuritySettings enrolled={false} required={false} homeHref="/dev" email="a@example.com" productName="Bridge" />
    );
    await confirmFails(new TypeError("Failed to fetch"), ok(me(true)), optional);
    fireEvent.click(cancelButton());
    expect((await screen.findByRole("alert")).textContent).toBe(NOT_SHOWN_TURN_OFF);
    expect(screen.getByRole("button", { name: "Turn off two-step sign-in" })).toBeTruthy();
  });

  it.each(LOST)("cancels with the delete advice once the server says it is off (%s)", async (_, failure) => {
    await confirmFails(failure(), ok(me(false)));
    fireEvent.click(cancelButton());
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(CANCELLED));
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("totp-key")).toBeNull();
  });

  it.each([
    ["no connection", () => new TypeError("Failed to fetch")],
    ["503", () => answer(503)],
    ["the session ended", () => answer(401, "unauthenticated")],
  ])("never advises deleting the entry when the status check fails (%s): reload to see", async (_, checkFails) => {
    const { container } = await confirmFails(new TypeError("Failed to fetch"), checkFails());
    fireEvent.click(cancelButton());

    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(UNKNOWN));
    expect(container.textContent).not.toMatch(/delete|cancelled/i);
    expect(screen.getByTestId("totp-key")).toBeTruthy(); // still on the setup steps: nothing was cancelled

    // Cancel asks again; this time the server answers, and it was on.
    mocks.get.mockResolvedValue(ok(me(true)));
    fireEvent.click(cancelButton());
    expect(await screen.findByText("Two-step sign-in is on.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe(NOT_SHOWN);
  });

  it("cancels at once, without asking the server, after only a wrong code (nothing was turned on)", async () => {
    await confirmFails(answer(401, "invalid_code"));
    fireEvent.click(cancelButton());
    expect(screen.getByRole("status").textContent).toBe(CANCELLED);
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("keeps asking the server after a lost answer, even if a later try got a wrong-code answer", async () => {
    await confirmFails(new TypeError("Failed to fetch"), ok(me(false)));
    mocks.post.mockResolvedValue(answer(401, "invalid_code"));
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "654321" } });
    fireEvent.click(confirmButton());
    await screen.findByText("That code did not work. Enter the newest code from your authenticator app.");
    fireEvent.click(cancelButton());
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(CANCELLED));
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("shows it on when a retried code finds no pending setup because the lost answer had turned it on", async () => {
    await confirmFails(new TypeError("Failed to fetch"), ok(me(true)));
    mocks.post.mockResolvedValue(answer(409, "no_pending_enrolment"));
    fireEvent.click(confirmButton());
    expect(await screen.findByText("Two-step sign-in is on.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe(NOT_SHOWN);
    expect(screen.queryByText("Start the setup again to get a new key.")).toBeNull();
  });

  it("stays on the setup steps, without the delete advice, when no pending setup is found and the check fails", async () => {
    const { container } = await confirmFails(answer(409, "no_pending_enrolment"), answer(503));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe(UNKNOWN));
    expect(screen.getByTestId("totp-key")).toBeTruthy();
    expect(container.textContent).not.toMatch(/delete|cancelled/i);
  });

  describe("focus after an API answer, which ends after an await", () => {
    // Outside React's event batching, a browser may commit the new screen only after the next animation frame (seen
    // in Chrome at 1440 px): focus must not wait for a frame, so here frames never come.
    beforeEach(() => vi.stubGlobal("requestAnimationFrame", () => 0));
    afterEach(() => vi.unstubAllGlobals());

    it("lands on the notice when two-step sign-in turned out to be on", async () => {
      await confirmFails(new TypeError("Failed to fetch"), ok(me(true)));
      fireEvent.click(cancelButton());
      await screen.findByText("Two-step sign-in is on.");
      expect(document.activeElement).toBe(screen.getByRole("alert"));
    });

    it("lands on the cancelled notice, one Tab before where setup starts again, when it turned out off", async () => {
      await confirmFails(new TypeError("Failed to fetch"), ok(me(false)));
      fireEvent.click(cancelButton());
      const field = await screen.findByLabelText(ENROL_FIELD, { selector: "input" });
      const notice = noticeReading(CANCELLED);
      expect(document.activeElement).toBe(notice);
      expect(nextInTabOrder(notice!)).toBe(field);
    });

    // The notices below show above the setup steps: at 360 px, more than a screen above Confirm and Cancel.
    it("lands on the 'could not check' notice when the check after Cancel fails", async () => {
      await confirmFails(new TypeError("Failed to fetch"), answer(503));
      fireEvent.click(cancelButton());
      const unknown = await screen.findByText(UNKNOWN);
      expect(document.activeElement).toBe(unknown.closest('[role="alert"]'));
    });

    it("lands on the 'could not check' notice when a retry finds no setup waiting and the check fails", async () => {
      await confirmFails(new TypeError("Failed to fetch"), answer(503));
      mocks.post.mockResolvedValue(answer(409, "no_pending_enrolment"));
      fireEvent.click(confirmButton());
      const unknown = await screen.findByText(UNKNOWN);
      expect(document.activeElement).toBe(unknown.closest('[role="alert"]'));
      expect(screen.getByTestId("totp-key")).toBeTruthy();
    });

    it("lands on the error when a confirmation gets no answer", async () => {
      await confirmFails(new TypeError("Failed to fetch"));
      const error = noticeReading("We could not reach the server. Check your connection, then try again.");
      expect(document.activeElement).toBe(error);
    });
  });

  it("ignores Confirm and Cancel while it asks the server", async () => {
    await confirmFails(new TypeError("Failed to fetch"), new Promise(() => {}));
    fireEvent.click(cancelButton());
    await waitFor(() => expect(cancelButton().getAttribute("aria-disabled")).toBe("true"));
    const busyConfirm = screen.getByRole("button", { name: "Checking…" }); // the Confirm button, busy
    expect(busyConfirm.getAttribute("aria-disabled")).toBe("true");

    fireEvent.click(busyConfirm);
    fireEvent.click(cancelButton());
    expect(mocks.post).toHaveBeenCalledTimes(2); // enrol and the one confirmation
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("totp-key")).toBeTruthy();
  });
});

describe("turning two-step sign-in off, where the role allows it", () => {
  // The "off" notice replaces the button that had focus, above the screen at 360 px: focus must reach it at once
  // (after an await, and with no animation frames here), or it falls to the page body.
  const optionalOn = (
    <SecuritySettings enrolled required={false} homeHref="/dev" email="a@example.com" productName="Bridge" />
  );
  beforeEach(() => vi.stubGlobal("requestAnimationFrame", () => 0));
  afterEach(() => vi.unstubAllGlobals());

  it("moves focus to the notice that it is off, with the start button ready", async () => {
    answerWith({ "/api/auth/totp/disable": answer(204) });
    page(true, optionalOn);
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-step sign-in" }));
    await screen.findByText("Two-step sign-in is off.");
    expect(document.activeElement).toBe(noticeReading("Two-step sign-in is off."));
    const start = screen.getByRole("button", { name: "Turn on two-step sign-in" }); // not left "Starting…"
    expect(start.getAttribute("aria-disabled")).toBeNull();
  });

  it("does the same when turning it off first asks for a fresh code", async () => {
    let disables = 0;
    mocks.post.mockImplementation((path: string) =>
      path === "/api/auth/totp/disable" && disables++ === 0 ? answer(403, "step_up_required") : answer(204),
    );
    page(true, optionalOn);
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-step sign-in" }));
    fireEvent.change(await screen.findByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm and turn off" }));
    await screen.findByText("Two-step sign-in is off.");
    expect(mocks.post.mock.calls.map(([path]) => path)).toEqual([
      "/api/auth/totp/disable",
      "/api/auth/step-up",
      "/api/auth/totp/disable",
    ]);
    expect(document.activeElement).toBe(noticeReading("Two-step sign-in is off."));
  });
});

describe("issuerOf", () => {
  it("reads the issuer an authenticator app shows, decoded", () => {
    expect(issuerOf(ENROLMENT.otpauth_uri)).toBe("Bridge");
    expect(issuerOf("otpauth://totp/Bridge%20Staging:a%40b.c?secret=K&issuer=Bridge%20Staging")).toBe("Bridge Staging");
  });

  it("is null when there is no issuer or the key cannot be read", () => {
    expect(issuerOf("otpauth://totp/a%40b.c?secret=K")).toBeNull();
    expect(issuerOf("otpauth://totp/a%40b.c?secret=K&issuer=%20")).toBeNull();
    expect(issuerOf("not a uri")).toBeNull();
  });
});

describe("StepUpForm", () => {
  it("is not left busy when the confirmed action ends without leaving the page (for example it failed)", async () => {
    mocks.post.mockResolvedValue(answer(200));
    const onConfirmed = vi.fn().mockResolvedValue(undefined); // turnOff settled an error and stayed here
    renderWithIntl(<StepUpForm onConfirmed={onConfirmed} busyLabel="Turning off…" />);
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.submit(screen.getByRole("button", { name: "Confirm and turn off" }).closest("form")!);
    await waitFor(() => expect(onConfirmed).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Confirm and turn off" }).getAttribute("aria-disabled")).toBeNull(),
    );
  });
});
