import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import NotificationSettingsPage from "./page";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD): in the public demo making, rotating and removing a calendar feed
// is switched off (the API refuses POST /api/me/calendar-feed and /api/orgs/{org_id}/calendar-feed), so the feed card
// keeps its heading and lead and shows the locked line instead of its controls. ("Add to calendar" on an item, the
// .ics download, has no demo branch.)

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
vi.mock("./feed-data", () => ({ feedStatus: async () => ({ active: true, last_fetched_at: null }) }));
vi.mock("./CalendarFeed", async () => {
  const { createElement } = await import("react");
  return { CalendarFeed: () => createElement("i", { "data-feed-controls": "" }) };
});
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (name === "data-saver" && state.cookie ? { value: state.cookie } : undefined),
  }),
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getMessages: async () => en,
  getLocale: async () => "en",
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/PortalNavFor", () => ({ PortalNavFor: () => null }));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

async function open() {
  const page = await NotificationSettingsPage({
    searchParams: Promise.resolve({}),
  } as PageProps<"/settings/notifications">);
  return renderWithIntl(<>{await resolveServerTree(page)}</>).container;
}

describe("Settings › Notifications › Calendar feed in the public demo", () => {
  it("shows the locked line instead of the feed's controls, and the controls with the mode off", async () => {
    state.side = "developer";
    vi.stubEnv("PUBLIC_DEMO", "true");
    let card = (await open()).querySelector<HTMLElement>("[data-calendar-feed-card]")!;
    expect(within(card).getByRole("heading", { name: en.calendarFeed.title })).toBeTruthy();
    expect(card.querySelector("[data-demo-locked]")!.textContent).toBe(en.publicDemo.locked);
    expect(card.querySelector("[data-feed-controls]")).toBeNull();
    expect(card.querySelector("[data-feed-private]")).toBeNull();
    cleanup();
    vi.stubEnv("PUBLIC_DEMO", "false");
    card = (await open()).querySelector<HTMLElement>("[data-calendar-feed-card]")!;
    expect(card.querySelector("[data-feed-controls]")).not.toBeNull();
    expect(card.querySelector("[data-demo-locked]")).toBeNull();
    expect(screen.queryByText(en.publicDemo.locked)).toBeNull();
  });
});
