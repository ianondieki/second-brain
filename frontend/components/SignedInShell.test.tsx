import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { DevNav } from "./DevNav";
import { SignedInShell, type SignedInShellProps } from "./SignedInShell";

// docs/spec/07 item 1 (REQ-UX-01): every signed-in screen has the top bar with the account menu, the portal's
// navigation when it has one (bottom tabs on phones, a left rail from 1024 px) and one column of content in <main>.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/dev",
}));

afterEach(cleanup);

async function renderShell(props: Omit<SignedInShellProps, "children">) {
  // SignedInShell is synchronous; its TopBar is a server component, resolved here as the server would.
  const tree = SignedInShell({ ...props, children: <h1>My ideas</h1> });
  renderWithIntl(<>{await resolveServerTree(tree)}</>);
  return screen.getByRole("main");
}

describe("SignedInShell", () => {
  it("puts the top bar, linking home to the portal, with the account menu above the page's main content", async () => {
    const main = await renderShell({ homeHref: "/dev" });
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Bridge (working name)" }).getAttribute("href")).toBe("/dev");
    const account = within(header).getByRole("button", { name: "Account" });
    fireEvent.click(account);
    expect(within(header).getByRole("link", { name: "Plan & billing" })).toBeTruthy();
    expect(header.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(main).getByRole("heading", { level: 1, name: "My ideas" })).toBeTruthy();
  });

  it("is the skip link's target: main#main takes focus without joining the tab order", async () => {
    const main = await renderShell({ homeHref: "/dev" });
    expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href")).toBe(`#${main.id}`);
    expect(main.id).toBe("main");
    expect(main.tabIndex).toBe(-1);
    main.focus();
    expect(document.activeElement).toBe(main);
  });

  it("puts the portal's navigation before the content and leaves room for the phone's tab bar", async () => {
    const main = await renderShell({ homeHref: "/dev", nav: <DevNav current="ideas" /> });
    const nav = screen.getByRole("navigation", { name: "Developer" });
    expect(nav.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(nav.parentElement).toBe(main.parentElement); // side by side from 1024 px
    expect(main.className.split(" ")).toEqual(expect.arrayContaining(["pb-28", "lg:pb-16"]));
  });

  it("without a navigation has no tab bar to clear", async () => {
    const main = await renderShell({ homeHref: "/org" });
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(main.className.split(" ")).toContain("pb-16");
    expect(main.className.split(" ")).not.toContain("pb-28");
  });

  it("keeps forms and summaries in a 36 rem column, and gives lists the full width when wide", async () => {
    const narrow = await renderShell({ homeHref: "/dev" });
    expect(narrow.firstElementChild!.className).toBe("max-w-xl");
    cleanup();
    const wide = await renderShell({ homeHref: "/dev", wide: true });
    expect(wide.firstElementChild!.hasAttribute("class")).toBe(false);
    expect(within(wide).getByRole("heading", { name: "My ideas" })).toBeTruthy();
  });
});
