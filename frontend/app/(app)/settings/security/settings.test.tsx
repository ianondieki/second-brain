import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { SecuritySettings } from "./SecuritySettings";
import { StepUpForm } from "./StepUpForm";

const mocks = vi.hoisted(() => ({ post: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args) } }));

function answer(status: number, code?: string) {
  const body = code ? JSON.stringify({ detail: { code, message: "server text" } }) : null;
  const error = code ? { detail: { code, message: "server text" } } : undefined;
  return { data: undefined, error, response: new Response(body, { status }) };
}

function page(passwordSet: boolean, children: ReactNode) {
  return renderWithIntl(<PasswordStateProvider initial={passwordSet}>{children}</PasswordStateProvider>);
}

const ENROL_FIELD = "Confirm with your current password";
const twoStep = <SecuritySettings enrolled={false} required homeHref="/org" email="a@example.com" />;

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
