import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { SignOutButton } from "./SignOutButton";

const mocks = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn(), post: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, refresh: mocks.refresh }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args) } }));

function answer(status: number) {
  const body = status === 204 ? null : JSON.stringify({ detail: { code: "x", message: "x" } });
  return { data: undefined, error: undefined, response: new Response(body, { status }) };
}

beforeEach(() => {
  mocks.replace.mockReset();
  mocks.refresh.mockReset();
  mocks.post.mockReset();
});
afterEach(cleanup);

describe("SignOutButton", () => {
  it.each([204, 401])("goes to /login and forgets the remembered email when logout answers %i", async (status) => {
    window.sessionStorage.setItem("bridge.pendingEmail", "wanjiru@example.com");
    mocks.post.mockResolvedValue(answer(status));
    renderWithIntl(<SignOutButton />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/login"));
    expect(window.sessionStorage.getItem("bridge.pendingEmail")).toBeNull();
    expect(mocks.post).toHaveBeenCalledWith("/api/auth/logout");
  });

  it.each([403, 500])("stays and warns when logout answers %i", async (status) => {
    window.sessionStorage.setItem("bridge.pendingEmail", "wanjiru@example.com");
    mocks.post.mockResolvedValue(answer(status));
    renderWithIntl(<SignOutButton />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect((await screen.findByRole("alert")).textContent).toContain("you may still be signed in");
    expect(screen.getByRole("button", { name: "Try signing out again" })).toBeTruthy();
    expect(mocks.replace).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("bridge.pendingEmail")).toBe("wanjiru@example.com");
  });

  it("stays and warns when the network fails, and the retry can succeed", async () => {
    mocks.post.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(answer(204));
    renderWithIntl(<SignOutButton />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(mocks.replace).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Try signing out again" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/login"));
  });
});
