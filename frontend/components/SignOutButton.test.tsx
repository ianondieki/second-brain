import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { SignOutButton } from "./SignOutButton";

const mocks = vi.hoisted(() => ({ replace: vi.fn(), refresh: vi.fn(), post: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, refresh: mocks.refresh }) }));
// The button sends through the CSRF-protected fetch only (lib/api/csrf), not the typed client.
vi.mock("@/lib/api/csrf", () => ({ withCsrf: () => (...args: unknown[]) => mocks.post(...args) }));

function answer(status: number) {
  const body = status === 204 ? null : JSON.stringify({ detail: { code: "x", message: "x" } });
  return new Response(body, { status });
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
    expect(mocks.post).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST" }));
  });

  // P25: a shared machine never shows the command palette's recent pages to the next person.
  it("forgets every account's recent pages on sign-out", async () => {
    window.localStorage.setItem("wazo-recent:v2:abc", JSON.stringify([{ href: "/org/inbox/x", title: "A title under NDA" }]));
    window.localStorage.setItem("wazo-theme", "dark");
    mocks.post.mockResolvedValue(answer(204));
    renderWithIntl(<SignOutButton />);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/login"));
    expect(window.localStorage.getItem("wazo-recent:v2:abc")).toBeNull();
    expect(window.localStorage.getItem("wazo-theme")).toBe("dark");
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
