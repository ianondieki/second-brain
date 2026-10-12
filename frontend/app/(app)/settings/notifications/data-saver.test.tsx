import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import NotificationSettingsPage from "./page";

// P27 track F (REQ-UX-08): Settings › Notifications carries the data-saver switch under "Data" for both sides (an
// organisation member has no Profile tab), the same component as Profile's, in the state of this device's cookie, and
// not a second primary action.

const state = vi.hoisted(() => ({ side: "org" as "org" | "developer", cookie: "1" as string | undefined }));

vi.mock("@/lib/api/server", () => ({
  requireMe: async () => ({
    side: state.side,
    user: { id: "u1" },
    memberships: [],
    mfa: { enrolled: true, required: false },
  }),
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET: async () => ({ data: [], response: { status: 200 } }) }),
}));
vi.mock("./preferences-data", () => ({ myPreferences: async () => [] }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (name === "data-saver" && state.cookie ? { value: state.cookie } : undefined),
  }),
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getMessages: async () => en,
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/PortalNavFor", () => ({ PortalNavFor: () => null }));

afterEach(cleanup);

async function open() {
  return renderWithIntl(<>{await resolveServerTree(await NotificationSettingsPage())}</>).container;
}

describe("Settings › Notifications › Data", () => {
  it.each(["org", "developer"] as const)(
    "holds the data-saver switch for a %s member, in this device's state",
    async (side) => {
      state.side = side;
      state.cookie = "1";
      const container = await open();
      const data = container.querySelector<HTMLElement>("[data-data-saver-card]")!;
      expect(within(data).getByRole("heading", { name: "Data" })).toBeTruthy();
      const toggle = within(data).getByRole("switch", { name: "Data saver" });
      expect(toggle.getAttribute("aria-checked")).toBe("true");
      expect(within(data).getByText("No photographs and the smallest images, on this device.")).toBeTruthy();
      expect(data.querySelector("[data-primary]")).toBeNull();
    },
  );

  it("shows the switch off without the cookie, even when there are no notification choices", async () => {
    state.side = "org";
    state.cookie = undefined;
    await open();
    expect(screen.getByRole("switch", { name: "Data saver" }).getAttribute("aria-checked")).toBe("false");
  });
});
