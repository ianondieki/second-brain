import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { LinkSignIn, scrubToken } from "./LinkSignIn";

const TOKEN = "tok_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456";

const mocks = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn(), post: vi.fn(), get: vi.fn(), forget: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, push: mocks.push }) }));
// P27 (D-69): the previous person's offline copies; continueAfterSignIn clears them too (lib/auth/session.test.ts).
vi.mock("@/components/offline/clear", () => ({ forgetOffline: (...args: unknown[]) => mocks.forget(...args) }));
vi.mock("@/lib/api/client", () => ({
  api: {
    POST: (...args: unknown[]) => mocks.post(...args),
    GET: (...args: unknown[]) => mocks.get(...args),
  },
}));

function ok(data: unknown) {
  return { data, error: undefined, response: new Response(JSON.stringify(data), { status: 200 }) };
}

function user(passwordSet: boolean) {
  return {
    id: "u1",
    email: "wanjiru@example.com",
    display_name: "Wanjiru",
    locale: "en",
    email_verified: true,
    password_set: passwordSet,
    staff_role: null,
    totp_enabled: false,
  };
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  // A router-style state that also holds the URL, as Next.js keeps it.
  window.history.replaceState({ __NA: true, url: `/auth/link#token=${TOKEN}` }, "", `/auth/link#token=${TOKEN}`);
});
afterEach(cleanup);

describe("LinkSignIn", () => {
  it("removes the token from the address bar and the history state as soon as it mounts", async () => {
    mocks.post.mockReturnValue(new Promise(() => {})); // consume still in flight
    renderWithIntl(<LinkSignIn />);
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
    expect(JSON.stringify(window.history.state)).not.toContain(TOKEN);
    expect(mocks.post).toHaveBeenCalledWith("/api/auth/magic-link/consume", { body: { token: TOKEN } });
  });

  it("keeps the token after a dropped connection and retries with it, without calling the link dead", async () => {
    mocks.post.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockReturnValueOnce(new Promise(() => {}));
    renderWithIntl(<LinkSignIn />);
    expect(await screen.findByRole("heading", { name: "Signing in did not finish" })).toBeTruthy();
    expect(screen.queryByText(/no longer works/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1]).toEqual(["/api/auth/magic-link/consume", { body: { token: TOKEN } }]);
  });

  it("offers to set a password, and a way home, when the account has none", async () => {
    window.sessionStorage.setItem("bridge.pendingEmail", "wanjiru@example.com");
    mocks.post.mockResolvedValue(ok({ mfa_required: false, user: user(false) }));
    mocks.get.mockResolvedValue(
      ok({
        side: "org",
        mfa: { required: true, enrolled: false, verified: false },
        memberships: [],
        user: user(false),
      }),
    );
    renderWithIntl(<LinkSignIn />);
    expect(await screen.findByRole("heading", { name: "You are signed in" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Set a password" }).getAttribute("href")).toBe(
      "/settings/security#password",
    );
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Continue without a password" }).getAttribute("href")).toBe("/org"),
    );
    expect(mocks.replace).not.toHaveBeenCalled();
    // The link signed the person in: the address kept for "Send the link again" is dropped.
    expect(window.sessionStorage.getItem("bridge.pendingEmail")).toBeNull();
  });

  // P27 (REQ-UX-08; D-69; security review): the no-password way on never reaches continueAfterSignIn, so the link
  // itself deletes the previous person's offline copies as soon as it has signed this one in.
  it("deletes this device's offline copies when the link signs someone in without a password", async () => {
    mocks.post.mockResolvedValue(ok({ mfa_required: false, user: user(false) }));
    mocks.get.mockResolvedValue(
      ok({ side: "developer", mfa: { required: false }, memberships: [], user: user(false) }),
    );
    renderWithIntl(<LinkSignIn />);
    expect(await screen.findByRole("heading", { name: "You are signed in" })).toBeTruthy();
    expect(mocks.forget).toHaveBeenCalledTimes(1);
  });

  it("deletes them before any routing when the account has a password", async () => {
    const order: string[] = [];
    mocks.forget.mockImplementation(async () => {
      order.push("forget");
    });
    mocks.replace.mockImplementation(() => order.push("route"));
    mocks.post.mockResolvedValue(ok({ mfa_required: true, user: user(true) }));
    renderWithIntl(<LinkSignIn />);
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/auth/mfa"));
    expect(order[0]).toBe("forget");
  });

  it("deletes nothing when the link does not sign anyone in", async () => {
    mocks.post.mockResolvedValue({
      data: undefined,
      error: { detail: { code: "invalid_or_expired_link", message: "x" } },
      response: new Response("{}", { status: 400 }),
    });
    renderWithIntl(<LinkSignIn />);
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("heading")).toBeTruthy());
    expect(mocks.forget).not.toHaveBeenCalled();
  });
});

describe("scrubToken", () => {
  it("removes the token from nested strings and keeps everything else", () => {
    const state = { tree: ["/auth/link", `#token=${TOKEN}`, { u: `/auth/link#token=${TOKEN}` }], n: 1, ok: true };
    expect(scrubToken(state, TOKEN)).toEqual({ tree: ["/auth/link", "", { u: "/auth/link" }], n: 1, ok: true });
  });
});
