import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { AccountMenu } from "./AccountMenu";

// P25 review: the account menu's lower part is a chunk of its own; when it cannot load (offline, or a newer deploy
// replaced it), the menu keeps a Sign out of its own instead of failing the page.

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("") }));
vi.mock("./AccountMenuExtras", () => {
  throw new Error("Failed to fetch dynamically imported module");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AccountMenu without its lower part", () => {
  it("keeps its links and a plain Sign out that ends the session and forgets this browser's recent pages", async () => {
    document.cookie = "bridge_csrf=token-1";
    window.localStorage.setItem("wazo-recent:v2:abc", "[]");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithIntl(<AccountMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("link", { name: "Help" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "token-1" } }));
    expect(window.localStorage.getItem("wazo-recent:v2:abc")).toBeNull();
  });

  it("sends the __Host- cookie's token first, and once more with a fresh token after a 403", async () => {
    const jar = vi.spyOn(document, "cookie", "get").mockReturnValue("bridge_csrf=planted; __Host-bridge_csrf=token-2");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("{}", { status: 403 }))
      .mockResolvedValueOnce(Response.json({ csrf_token: "token-3" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    renderWithIntl(<AccountMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    const tokens = fetchMock.mock.calls
      .filter(([url]) => url === "/api/auth/logout")
      .map(([, init]) => (init?.headers as Record<string, string>)["X-CSRF-Token"]);
    expect(tokens).toEqual(["token-2", "token-3"]);
    jar.mockRestore();
  });

  it("says to try again when the sign-out does not go through", async () => {
    document.cookie = "bridge_csrf=token-1";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(new Response("{}", { status: 500 })));
    renderWithIntl(<AccountMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Try signing out again" })).toBeTruthy();
  });
});
