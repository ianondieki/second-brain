import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { AuthShell } from "./AuthShell";
import { PortalLoading } from "./loading/PortalLoading";

// D-67 (P25; REQ-UX-01, REQ-UX-05, REQ-UX-06): the signed-out screens' split layout (a credited photograph on the night
// side from 1024 px only, the form alone on a phone, one primary action from the page) and the loading screens (the
// page's own shell, one "Loading…" for assistive technology, skeletons that say nothing).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/components/TopBar", () => ({
  TopBar: ({ children, homeHref }: { children?: ReactNode; homeHref?: string }) => (
    <header data-top-bar={homeHref ?? "/"}>{children}</header>
  ),
}));

afterEach(cleanup);

describe("AuthShell", () => {
  it("puts the form first, and the night side's photograph only behind sources that match from 1024 px", async () => {
    const { container } = renderWithIntl(
      <>
        {await resolveServerTree(
          await AuthShell({
            children: (
              <button type="submit" data-primary="">
                Log in
              </button>
            ),
          }),
        )}
      </>,
    );
    const main = screen.getByRole("main");
    expect(within(main).getByRole("button", { name: "Log in" })).toBeTruthy();
    const side = container.querySelector<HTMLElement>("aside")!;
    expect(side.className).toContain("hidden");
    expect(side.className).toContain("lg:block");
    expect(side.dataset.authPhoto).toBe("nairobi-jacaranda");
    // The photograph: decorative, and nothing fetched on a phone (every <source> is for 1024 px and up; the <img>
    // itself is a transparent pixel).
    const sources = side.querySelectorAll("source");
    expect(sources.length).toBeGreaterThan(0);
    for (const source of sources) expect(source.getAttribute("media")).toBe("(min-width: 64rem)");
    const img = side.querySelector("img")!;
    expect(img.getAttribute("alt")).toBe("");
    expect(img.getAttribute("src")).toMatch(/^data:image\/gif/);
    // Credited beside it, and on /credits.
    const credit = side.querySelector("[data-photo-credit]")!;
    expect(credit.textContent).toContain("McKay Savage");
    expect(within(credit as HTMLElement).getByRole("link", { name: "All photo credits" }).getAttribute("href")).toBe("/credits");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    // Server-rendered: no script of its own (the split is CSS).
    expect(container.querySelector("script")).toBeNull();
  });

  it("takes the golden-hour photograph for creating an account", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(await AuthShell({ children: <p>Form</p>, photo: "signUp" }))}</>);
    expect(container.querySelector<HTMLElement>("aside")!.dataset.authPhoto).toBe("nairobi-golden-hour");
  });
});

describe("PortalLoading", () => {
  it("draws the page's frame and says Loading once; the skeletons say nothing", async () => {
    const { container } = renderWithIntl(
      <>{await resolveServerTree(await PortalLoading({ homeHref: "/org", nav: <nav aria-label="Organisation" />, shape: "cards", tabs: true }))}</>,
    );
    const bar = container.querySelector<HTMLElement>("[data-top-bar]")!;
    expect(bar.querySelector("a")?.getAttribute("href")).toBe("/org");
    expect(within(screen.getByRole("main")).getByRole("status")).toBeTruthy();
    // Search, the bell and the account menu stand in as shapes (no client code: prefetching this screen fetches no
    // route script).
    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    expect(bar.querySelector("[data-top-bar-controls]")?.getAttribute("aria-hidden")).toBe("true");
    expect(screen.getByRole("navigation", { name: "Organisation" })).toBeTruthy();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe("Loading…");
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
    for (const block of container.querySelectorAll("[data-skeleton]")) expect(block.closest("[aria-hidden='true']")).not.toBeNull();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(container.querySelector("[data-loading-shape='cards']")).not.toBeNull();
  });

  it("has a shape for each kind of page", async () => {
    for (const shape of ["home", "list", "table", "detail", "form"] as const) {
      const { container, unmount } = renderWithIntl(<>{await resolveServerTree(await PortalLoading({ homeHref: "/admin", shape }))}</>);
      expect(container.querySelector(`[data-loading-shape='${shape}']`)).not.toBeNull();
      expect(container.querySelectorAll("[data-skeleton]").length).toBeGreaterThan(2);
      unmount();
    }
  });
});
