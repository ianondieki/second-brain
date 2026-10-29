import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { NotFoundScreen } from "./NotFoundScreen";

// P16 (REQ-UX-02): an address with no page keeps the product's top bar, with one sentence and one link home
// (docs/spec/07 item 4), instead of Next's bare default. Static: it reads no session and ships no client component,
// since Next.js embeds it in every page's payload.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
const me = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ getMe: me.get }));

afterEach(cleanup);

async function renderScreen() {
  renderWithIntl(<>{await resolveServerTree(<NotFoundScreen />)}</>);
}

describe("the not-found screen", () => {
  it("says there is no page, with one link home as the one primary action", async () => {
    await renderScreen();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Page not found");
    const empty = document.querySelector("[data-empty-state]")!;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.textContent).toContain("There is no page at this address.");
    expect(screen.getByRole("link", { name: "Go to the home page" }).getAttribute("href")).toBe("/");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("keeps the top bar and reads no session", async () => {
    await renderScreen();
    expect(screen.getByRole("link", { name: "Wazo" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "Skip to content" })).toBeTruthy();
    expect(document.querySelector("[data-account-menu]")).toBeNull();
    expect(me.get).not.toHaveBeenCalled();
  });
});
