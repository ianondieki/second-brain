import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { NotificationBell, UnreadNotificationBell } from "./NotificationBell";

// P19-C (REQ-NOT-03 in-app channel, docs/spec/07 item 1): the top bar's bell links to /notifications and carries the
// unread count as a small badge and in its accessible name; the count is read on the server with the page.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
const unread = vi.hoisted(() => ({ read: vi.fn<() => Promise<number | null>>() }));
vi.mock("@/lib/api/server", () => ({ getUnreadCount: () => unread.read() }));

afterEach(() => {
  cleanup();
  unread.read.mockReset();
});

async function renderTree(node: ReactNode) {
  renderWithIntl(<>{await resolveServerTree(node)}</>);
}

function badge() {
  return document.querySelector("[data-unread-badge]");
}

describe("NotificationBell", () => {
  it("at 0 is a link to the Notifications page named Notifications, with no badge", async () => {
    await renderTree(<NotificationBell count={0} />);
    const bell = screen.getByRole("link", { name: "Notifications" });
    expect(bell.getAttribute("href")).toBe("/notifications");
    expect(badge()).toBeNull();
    expect(bell.className.split(" ")).toContain("size-11"); // a 44 px target (docs/spec/07 item 6)
  });

  it("at 3 reads 'Notifications, 3 unread' and shows 3 on the badge, hidden from the accessible name's double", async () => {
    await renderTree(<NotificationBell count={3} />);
    const bell = screen.getByRole("link", { name: "Notifications, 3 unread" });
    expect(badge()?.textContent).toBe("3");
    expect(badge()?.getAttribute("aria-hidden")).toBe("true");
    expect(bell.contains(badge())).toBe(true);
  });

  it("above 99 shows '99+' on the badge and keeps the real number in the name", async () => {
    await renderTree(<NotificationBell count={120} />);
    expect(screen.getByRole("link", { name: "Notifications, 120 unread" })).toBeTruthy();
    expect(badge()?.textContent).toBe("99+");
  });

  it("shows exactly 99 as 99", async () => {
    await renderTree(<NotificationBell count={99} />);
    expect(badge()?.textContent).toBe("99");
  });

  it("with an unknown count is the plain link, no badge", async () => {
    await renderTree(<NotificationBell count={null} />);
    expect(screen.getByRole("link", { name: "Notifications" })).toBeTruthy();
    expect(badge()).toBeNull();
  });
});

describe("the bell's name in Swahili", () => {
  it("says one and many in their own forms", () => {
    const t = createTranslator({ locale: "sw", messages: sw, namespace: "notifications.bell" });
    expect(t("unread", { count: 1 })).toBe("Arifa, 1 haijasomwa");
    expect(t("unread", { count: 3 })).toBe("Arifa, 3 hazijasomwa");
  });
});

describe("UnreadNotificationBell", () => {
  it("reads the count on the server with the page", async () => {
    unread.read.mockResolvedValue(3);
    await renderTree(<UnreadNotificationBell />);
    expect(screen.getByRole("link", { name: "Notifications, 3 unread" })).toBeTruthy();
    expect(unread.read).toHaveBeenCalledTimes(1);
  });

  it("never holds the top bar up: a failed read is a bell with no count", async () => {
    unread.read.mockRejectedValue(new Error("down"));
    await renderTree(<UnreadNotificationBell />);
    expect(screen.getByRole("link", { name: "Notifications" })).toBeTruthy();
    expect(badge()).toBeNull();
  });
});
