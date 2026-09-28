import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { issuerOf, SecuritySettings } from "./SecuritySettings";
import { StepUpForm } from "./StepUpForm";

const mocks = vi.hoisted(() => ({ post: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args) } }));

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

/** Answers each API path with the given result; the rest with 204. */
function answerWith(answers: Record<string, unknown>) {
  mocks.post.mockImplementation((path: string) => answers[path] ?? answer(204));
}

function page(passwordSet: boolean, children: ReactNode) {
  return renderWithIntl(<PasswordStateProvider initial={passwordSet}>{children}</PasswordStateProvider>);
}

/** The `autocomplete="username"` fields in the form that holds this password field. */
function usernameFields(passwordField: HTMLElement) {
  return [...passwordField.closest("form")!.querySelectorAll<HTMLInputElement>('input[autocomplete="username"]')];
}

const ENROL_FIELD = "Confirm with your current password";
const CANCELLED = "Setup cancelled. If you added Bridge to your authenticator app, delete that entry.";
const twoStep = (
  <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" productName="Bridge" />
);

beforeEach(() => {
  mocks.post.mockReset();
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

  async function startSetup() {
    fireEvent.change(screen.getByLabelText(ENROL_FIELD, { selector: "input" }), { target: { value: "jacaranda" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    await screen.findByTestId("totp-key");
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
    // Focus goes where setup starts again (the password it asks for), not to the top of the page.
    const field = screen.getByLabelText(ENROL_FIELD, { selector: "input" });
    await waitFor(() => expect(document.activeElement).toBe(field));
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

  it("puts focus on the start button after cancelling when the account has no password", async () => {
    answerWith({ "/api/auth/totp/enrol": ok(ENROLMENT) });
    page(false, twoStep);
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    await screen.findByTestId("totp-key");
    fireEvent.click(screen.getByRole("button", { name: "Cancel setup" }));
    const start = screen.getByRole("button", { name: "Turn on two-step sign-in" });
    await waitFor(() => expect(document.activeElement).toBe(start));
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
    });
    securityPage();
    await startSetup();

    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await screen.findByRole("button", { name: "Turn on two-step sign-in" });
    expect(passwordSection()).not.toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy(); // the error says why; no "cancelled" line
    expect(screen.queryByText(CANCELLED)).toBeNull();
    // Focus is not left on the page body: it goes where setup starts again.
    const field = screen.getByLabelText(ENROL_FIELD, { selector: "input" });
    await waitFor(() => expect(document.activeElement).toBe(field));
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
