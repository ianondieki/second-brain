import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { Children, isValidElement, Suspense, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { DevNav } from "./DevNav";
import { NotificationBell, UnreadNotificationBell } from "./NotificationBell";
import { SignedInShell, type SignedInShellProps } from "./SignedInShell";

// docs/spec/07 item 1 (REQ-UX-01): every signed-in screen has the top bar with the account menu, the portal's
// navigation when it has one (bottom tabs on phones, a left rail from 1024 px) and one column of content in <main>.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/dev",
}));
vi.mock("@/lib/api/server", () => ({ getUnreadCount: async () => 2 }));

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
    expect(within(header).getByRole("link", { name: "Wazo" }).getAttribute("href")).toBe("/dev");
    const account = within(header).getByRole("button", { name: "Account" });
    fireEvent.click(account);
    expect(within(header).getByRole("link", { name: "Plan & billing" })).toBeTruthy();
    expect(header.compareDocumentPosition(main) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(main).getByRole("heading", { level: 1, name: "My ideas" })).toBeTruthy();
    // D-65: the signed-in top bar carries no Prototype badge and no lattice band.
    expect(within(header).queryByText("Prototype")).toBeNull();
    expect(header.querySelector("[data-lattice]")).toBeNull();
  });

  // P25 (D-67): Search comes first among the controls; from 1024 px the bar stays at the top.
  it("puts the Search button before the bell, in a top bar that is sticky from 1024 px", async () => {
    await renderShell({ homeHref: "/dev" });
    const header = screen.getByRole("banner");
    const search = within(header).getByRole("button", { name: "Search or jump to" });
    expect(search.getAttribute("aria-haspopup")).toBe("dialog");
    const bell = within(header).getByRole("link", { name: "Notifications, 2 unread" });
    expect(search.compareDocumentPosition(bell) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(header.className.split(" ")).toEqual(expect.arrayContaining(["lg:sticky", "lg:top-0"]));
    expect(header.hasAttribute("data-sticky")).toBe(true);
  });

  it("puts the bell, with the unread count read on the server, before the account menu (P19-C)", async () => {
    await renderShell({ homeHref: "/dev" });
    const header = screen.getByRole("banner");
    const bell = within(header).getByRole("link", { name: "Notifications, 2 unread" });
    expect(bell.getAttribute("href")).toBe("/notifications");
    const account = within(header).getByRole("button", { name: "Account" });
    expect(bell.compareDocumentPosition(account) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("holds the bell in a Suspense boundary whose fallback is the bell without a count", () => {
    function find(
      node: ReactNode,
    ): ReactElement<{ fallback: ReactElement<{ count: unknown }>; children: ReactElement }> | null {
      for (const child of Children.toArray(node)) {
        if (!isValidElement(child)) continue;
        if (child.type === Suspense) return child as never;
        const found = find((child.props as { children?: ReactNode }).children);
        if (found) return found;
      }
      return null;
    }
    const boundary = find(SignedInShell({ homeHref: "/dev", children: null }));
    expect(boundary).not.toBeNull();
    expect(boundary!.props.fallback.type).toBe(NotificationBell);
    expect(boundary!.props.fallback.props.count).toBeNull();
    expect(boundary!.props.children.type).toBe(UnreadNotificationBell);
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
    // Side by side from 1024 px: the rail (the nav and, under it, Help; P25) beside main.
    expect(nav.closest("[data-portal-rail]")!.parentElement).toBe(main.parentElement);
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

  // P27 (REQ-ENG-14): the Board's columns run on past the 72 rem frame to the window's right edge, the rail where every
  // other page has it (the frame's own left padding), never wider than the body (no sideways scroll).
  it("lets a bleeding page run on to the window's right edge, the rail left where the frame puts it", async () => {
    const framed = await renderShell({ homeHref: "/org", wide: true });
    expect(framed.parentElement!.className.split(" ")).toEqual(expect.arrayContaining(["mx-auto", "max-w-6xl"]));
    expect(framed.parentElement!.hasAttribute("data-bleed")).toBe(false);
    cleanup();
    const main = await renderShell({ homeHref: "/org", bleed: true });
    const row = main.parentElement!;
    expect(row.hasAttribute("data-bleed")).toBe(true);
    expect(row.className.split(" ")).not.toContain("max-w-6xl");
    expect(row.className.split(" ")).toEqual(
      expect.arrayContaining(["lg:pr-6", "lg:pl-[max(1.5rem,calc((100%_-_72rem)/2_+_1.5rem))]"]),
    );
    // The content is not held to the form column.
    expect(main.firstElementChild!.hasAttribute("class")).toBe(false);
  });

  // P27 (REQ-UX-08; D-69): the offline part, given by the pages the worker keeps, sits at the top of <main>, above the
  // page; never in the staff console.
  it("draws the offline part it is given at the top of main, and none in the staff console", async () => {
    const main = await renderShell({ homeHref: "/dev", offline: <p data-offline-part="">offline</p> });
    expect(main.firstElementChild!.hasAttribute("data-offline-part")).toBe(true);
    cleanup();
    const console = await renderShell({
      homeHref: "/admin",
      staffRole: "admin",
      offline: <p data-offline-part="">offline</p>,
    });
    expect(console.querySelector("[data-offline-part]")).toBeNull();
  });
});
