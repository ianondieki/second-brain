import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignedInShell } from "@/components/SignedInShell";
import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import HelpPage from "./page";
import { HELP_SECTIONS } from "./sections";

// docs/spec/07 item 1 (avatar menu "Help") and every email footer's "Help" (docs/spec/06 6.10): a public page of
// short plain answers, with the account menu when signed in, and no primary action of its own.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getMessages: async () => en,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({}) }));
const me = vi.hoisted(() => ({ get: vi.fn(), unread: vi.fn(async () => null) }));
vi.mock("@/lib/api/server", () => ({ getMe: me.get, getUnreadCount: me.unread }));

afterEach(() => {
  cleanup();
  me.get.mockReset();
});

/** Whether the element tree holds a help section with this id (through every `children`). */
function hasSection(node: ReactNode, id: string): boolean {
  if (Array.isArray(node)) return node.some((child) => hasSection(child, id));
  if (!isValidElement(node)) return false;
  const props = node.props as { "data-help-section"?: string; children?: ReactNode };
  return props["data-help-section"] === id || hasSection(props.children, id);
}

async function renderSignedOut() {
  renderWithIntl(<>{await resolveServerTree(await HelpPage())}</>);
}

describe("the help page", () => {
  it("answers pitching, confidentiality, reminders and support, in that order", async () => {
    me.get.mockResolvedValue(null);
    await renderSignedOut();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Help");
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "How pitching works",
      "What stays confidential",
      "Reminders",
      "Contact support",
    ]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("explains Tier 1 and Tier 2 in the approved phrasing", async () => {
    me.get.mockResolvedValue(null);
    await renderSignedOut();
    const section = document.querySelector("[data-help-section='confidential']") as HTMLElement;
    expect(section.textContent).toContain("Tier 1 is the public teaser");
    expect(section.textContent).toContain(
      "shown to verified people at organisations that accepted our NDA, plus platform staff under logged, owner-notified break-glass",
    );
    expect(section.textContent).toContain("every view is logged and watermarked to the viewer");
    expect(section.textContent).toContain("timestamped evidence of what you submitted and when");
  });

  it("links reminders to the notification settings", async () => {
    me.get.mockResolvedValue(null);
    await renderSignedOut();
    const section = document.querySelector("[data-help-section='reminders']") as HTMLElement;
    expect(within(section).getByRole("link", { name: "Notifications" }).getAttribute("href")).toBe("/settings/notifications");
  });

  it("gives no support address or phone until one is set", async () => {
    me.get.mockResolvedValue(null);
    await renderSignedOut();
    const support = document.querySelector("[data-help-section='support']") as HTMLElement;
    expect(support.querySelector("[data-support-placeholder]")?.textContent).toBe("Support contact to be set.");
    expect(support.textContent).not.toMatch(/@|\+?\d{3}[\s-]?\d{3}/);
    expect(within(support).queryAllByRole("link")).toHaveLength(0);
  });

  it("offers Log in to a visitor, and opens even when the API cannot say who is signed in", async () => {
    me.get.mockRejectedValue(new Error("GET /api/auth/me answered 503"));
    await renderSignedOut();
    expect(screen.getByRole("link", { name: "Log in" }).getAttribute("href")).toBe("/login");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Help");
  });

  it("opens in the signed-in shell, with the account menu, for someone signed in", async () => {
    me.get.mockResolvedValue({ side: "org", mfa: { enrolled: true, verified: true, required: true }, user: {} });
    const page = await HelpPage();
    expect(isValidElement(page) && page.type).toBe(SignedInShell);
    expect((page as ReactElement<{ homeHref: string }>).props.homeHref).toBe("/org");
    expect(me.unread).toHaveBeenCalled(); // the bell's count, started beside /api/auth/me (P19-C)
  });

  it("offers the tour again to a portal, not to the staff console", async () => {
    // The signed-in shell holds an async top bar, so the page is inspected as the tree it returns.
    me.get.mockResolvedValue({ side: "developer", mfa: { enrolled: false, verified: false, required: false }, user: {} });
    const dev = await HelpPage();
    expect(hasSection(dev, "tour")).toBe(true);
    expect(hasSection(dev, "support")).toBe(true);
    me.get.mockResolvedValue({ side: "staff", mfa: { enrolled: true, verified: true, required: true }, user: { staff_role: "admin" } });
    const staff = await HelpPage();
    expect(isValidElement(staff) && (staff as ReactElement<{ homeHref: string }>).props.homeHref).toBe("/admin");
    expect(hasSection(staff, "tour")).toBe(false);
    expect(hasSection(staff, "support")).toBe(true);
  });

  it("treats a session still owing its second factor as a visitor", async () => {
    me.get.mockResolvedValue({ side: "pending", mfa: { enrolled: true, verified: false, required: true }, user: {} });
    await renderSignedOut();
    expect(screen.getByRole("link", { name: "Log in" })).toBeTruthy();
  });

  it("has every paragraph in both languages", () => {
    const help = (tree: unknown, key: string) =>
      key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], (tree as { help: unknown }).help);
    for (const { id, paragraphs } of HELP_SECTIONS) {
      for (const key of [`${id}.title`, ...paragraphs]) {
        expect(typeof help(en, key), key).toBe("string");
        expect(typeof help(sw, key), key).toBe("string");
      }
    }
  });
});
