import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { NotFoundScreen } from "./NotFoundScreen";

// P16 (REQ-UX-02): an address with no page keeps the product's frame, with one sentence and one link home
// (docs/spec/07 item 4), instead of Next's bare default. The same answer for every unknown address.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({}) }));
// The top bar is an async server component, which React's client renderer cannot run: a stand-in keeps its slot.
vi.mock("./TopBar", () => ({ TopBar: ({ children }: { children?: React.ReactNode }) => <header>{children}</header> }));
const me = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ getMe: me.get }));

afterEach(() => {
  cleanup();
  me.get.mockReset();
});

const DEVELOPER = {
  side: "developer",
  mfa: { enrolled: false, verified: false, required: false },
  user: { id: "u1", display_name: "Wanjiru", staff_role: null },
};

async function renderScreen() {
  renderWithIntl(<>{await resolveServerTree(<NotFoundScreen />)}</>);
}

describe("the not-found screen", () => {
  it("says there is no page, with one link home and nothing else to do", async () => {
    me.get.mockResolvedValue(null);
    await renderScreen();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Page not found");
    const empty = document.querySelector("[data-empty-state]")!;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.textContent).toContain("There is no page at this address.");
    const home = screen.getByRole("link", { name: "Go to the home page" });
    expect(home.getAttribute("href")).toBe("/");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("keeps the signed-in frame and links a signed-in person to their own home", async () => {
    me.get.mockResolvedValue(DEVELOPER);
    await renderScreen();
    expect(screen.getByRole("link", { name: "Go to your home page" }).getAttribute("href")).toBe("/dev");
    expect(document.querySelector("[data-account-menu]")).not.toBeNull();
  });

  it("shows the signed-out frame when the API cannot say who is asking", async () => {
    me.get.mockRejectedValue(new Error("GET /api/auth/me answered 503"));
    await renderScreen();
    expect(screen.getByRole("link", { name: "Go to the home page" })).toBeTruthy();
    expect(document.querySelector("[data-account-menu]")).toBeNull();
  });
});
