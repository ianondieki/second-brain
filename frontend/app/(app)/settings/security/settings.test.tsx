import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PasswordSettings } from "./PasswordSettings";
import { StepUpForm } from "./StepUpForm";

const mocks = vi.hoisted(() => ({ post: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args) } }));

function answer(status: number, code?: string) {
  const body = code ? JSON.stringify({ detail: { code, message: "server text" } }) : null;
  const error = code ? { detail: { code, message: "server text" } } : undefined;
  return { data: undefined, error, response: new Response(body, { status }) };
}

beforeEach(() => {
  mocks.post.mockReset();
  mocks.push.mockReset();
});
afterEach(cleanup);

describe("PasswordSettings", () => {
  it("asks for the current password only when the account has one", () => {
    renderWithIntl(<PasswordSettings email="a@example.com" passwordSet />);
    expect(screen.getByLabelText("Current password", { selector: "input" })).toBeTruthy();
    cleanup();
    renderWithIntl(<PasswordSettings email="a@example.com" passwordSet={false} />);
    expect(screen.queryByLabelText("Current password", { selector: "input" })).toBeNull();
    expect(screen.getByLabelText("New password", { selector: "input" })).toBeTruthy();
  });

  it("links to the login page when the session has ended", async () => {
    mocks.post.mockResolvedValue(answer(401, "unauthenticated"));
    renderWithIntl(<PasswordSettings email="a@example.com" passwordSet={false} />);
    fireEvent.change(screen.getByLabelText("New password", { selector: "input" }), {
      target: { value: "a long enough password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    expect((await screen.findByRole("link", { name: "Log in again" })).getAttribute("href")).toBe("/login");
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
