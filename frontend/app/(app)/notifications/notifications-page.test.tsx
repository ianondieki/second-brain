import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { isValidElement, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PortalNavFor } from "@/components/PortalNavFor";
import { SignedInShell, type SignedInShellProps } from "@/components/SignedInShell";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Notification } from "./NotificationList";
import NotificationsPage from "./page";

// P19-C (REQ-NOT-03 in-app channel; docs/spec/07 items 1, 2, 4): the Notifications page in the person's own portal,
// grouped by Nairobi day, unread marked by a mark, words and weight, rows that are links, one empty state of one
// sentence and one action, "Mark all as read" the one secondary action, and the inbox's cursor paging.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/notifications",
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));

const api = vi.hoisted(() => ({
  me: vi.fn(),
  list: vi.fn(),
  unread: vi.fn<() => Promise<number | null>>(),
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: api.me,
  getUnreadCount: api.unread,
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET: api.list }),
}));

const DEV_ME = { side: "developer", mfa: { enrolled: true, verified: true, required: false }, user: { staff_role: null } };
const ORG_ME = { ...DEV_ME, side: "org" };

function note(id: string, created_at: string, extra: Partial<Notification> = {}): Notification {
  return {
    id,
    kind: "engagement.n03",
    title: `Title ${id}`,
    body: `Body ${id}.`,
    link: `/dev/engagements/e-${id}`,
    created_at,
    read_at: null,
    ...extra,
  };
}

function listAnswers(items: Notification[], next_cursor: string | null = null, status = 200) {
  api.list.mockResolvedValue(
    status === 200 ? { data: { items, next_cursor }, response: new Response(null, { status }) } : { response: new Response(null, { status }) },
  );
}

async function open(searchParams: Record<string, string> = {}) {
  const element = await NotificationsPage({ searchParams: Promise.resolve(searchParams), params: Promise.resolve({}) } as never);
  expect(isValidElement(element) && element.type).toBe(SignedInShell);
  const props = (element as ReactElement<SignedInShellProps>).props;
  renderWithIntl(<>{await resolveServerTree(SignedInShell(props))}</>);
  return props;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-02T09:00:00Z")); // 12:00 EAT, 2 Oct 2026
  api.me.mockResolvedValue(DEV_ME);
  api.unread.mockResolvedValue(2);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("the Notifications page", () => {
  it.each([
    ["developer", DEV_ME, "/dev"],
    ["org", ORG_ME, "/org"],
  ])("keeps the %s portal's navigation, wide, linking home to its portal", async (_, me, home) => {
    api.me.mockResolvedValue(me);
    listAnswers([]);
    const props = await open();
    expect(props.homeHref).toBe(home);
    expect(props.wide).toBe(true);
    expect(isValidElement(props.nav) && props.nav.type).toBe(PortalNavFor);
    expect(screen.getByRole("heading", { level: 1, name: "Notifications" })).toBeTruthy();
  });

  it("groups by Nairobi day, newest first: Today, Yesterday, then the date", async () => {
    listAnswers([
      note("a", "2026-10-02T08:30:00Z"),
      note("b", "2026-10-01T22:00:00Z"), // 01:00 EAT on 2 Oct
      note("c", "2026-10-01T10:15:00Z", { read_at: "2026-10-01T11:00:00Z" }),
      note("d", "2026-09-28T06:05:00Z", { read_at: "2026-09-28T07:00:00Z" }),
    ]);
    await open();
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Today",
      "Yesterday",
      "28 Sep 2026",
    ]);
    const today = within(main).getByRole("region", { name: "Today" });
    expect([...today.querySelectorAll("[data-notification]")].map((row) => row.getAttribute("data-notification"))).toEqual(["a", "b"]);
    // Each row: the title, the body and the time in EAT.
    const first = today.querySelector<HTMLElement>("[data-notification='a']")!;
    expect(within(first).getByText("Body a.")).toBeTruthy();
    const time = first.querySelector("time")!;
    expect(time.textContent).toBe("11:30 EAT");
    expect(time.getAttribute("dateTime")).toBe("2026-10-02T08:30:00Z");
    expect(today.querySelector("[data-notification='b'] time")?.textContent).toBe("01:00 EAT");
  });

  it("marks unread rows by words, weight and the mark; read rows by none of them", async () => {
    listAnswers([note("a", "2026-10-02T08:30:00Z"), note("c", "2026-10-02T07:00:00Z", { read_at: "2026-10-02T07:30:00Z" })]);
    await open();
    const unread = document.querySelector<HTMLElement>("[data-notification='a']")!;
    expect(unread.getAttribute("data-unread")).toBe("true");
    // jsdom joins the hidden word and the title without the space a browser puts after the (blockified) sr-only span.
    const link = within(unread).getByRole("link", { name: /^Unread\s?Title a$/ });
    expect(link.getAttribute("href")).toBe("/dev/engagements/e-a");
    expect(within(link).getByText("Title a").className).toContain("font-semibold");
    expect(link.className).toContain("after:inset-0"); // the whole row is the target
    const read = document.querySelector<HTMLElement>("[data-notification='c']")!;
    expect(read.getAttribute("data-unread")).toBe("false");
    expect(within(read).getByRole("link", { name: "Title c" })).toBeTruthy();
    expect(within(read).getByText("Title c").className).toContain("font-normal");
  });

  it("shows a row without a link as plain text, not a link", async () => {
    listAnswers([note("a", "2026-10-02T08:30:00Z", { link: null, body: null })]);
    await open();
    const row = document.querySelector<HTMLElement>("[data-notification='a']")!;
    expect(within(row).queryByRole("link")).toBeNull();
    expect(within(row).getByRole("heading", { level: 3 }).textContent).toBe("UnreadTitle a");
    expect(row.querySelectorAll("p")).toHaveLength(0); // no body line
  });

  it("offers Mark all as read as the one secondary action, never a primary one", async () => {
    listAnswers([note("a", "2026-10-02T08:30:00Z")]);
    await open();
    const action = screen.getByRole("button", { name: "Mark all as read" });
    expect(action).toHaveProperty("disabled", false);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("disables Mark all as read when nothing is unread", async () => {
    api.unread.mockResolvedValue(0);
    listAnswers([note("c", "2026-10-02T07:00:00Z", { read_at: "2026-10-02T07:30:00Z" })]);
    await open();
    expect(screen.getByRole("button", { name: "Mark all as read" })).toHaveProperty("disabled", true);
  });

  it("with the count unknown, lets this page's unread rows decide", async () => {
    api.unread.mockResolvedValue(null);
    listAnswers([note("a", "2026-10-02T08:30:00Z")]);
    await open();
    expect(screen.getByRole("button", { name: "Mark all as read" })).toHaveProperty("disabled", false);
  });

  it("is one sentence and one action home when there is nothing", async () => {
    api.me.mockResolvedValue(ORG_ME);
    api.unread.mockResolvedValue(0);
    listAnswers([]);
    await open();
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(within(empty).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([
      "Nothing yet: new proposals, scout matches and engagement updates for your organisation will land here.",
    ]);
    const links = within(empty).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([["Go to your home page", "/org"]]);
    expect(screen.queryByRole("button", { name: "Mark all as read" })).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it.each([
    ["a developer", DEV_ME, "Nothing yet: your tracker updates and approvals will land here.", "/dev"],
    [
      "staff",
      { ...DEV_ME, side: "staff", user: { staff_role: "moderator" } },
      "Nothing yet: moderation and research notices will land here.",
      "/admin",
    ],
  ])("says what lands here for %s when there is nothing", async (_, me, sentence, home) => {
    api.me.mockResolvedValue(me);
    api.unread.mockResolvedValue(0);
    listAnswers([]);
    await open();
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(within(empty).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([sentence]);
    expect(within(empty).getByRole("link").getAttribute("href")).toBe(home);
  });

  it("pages with the API's cursor: Older notifications, then back to the newest", async () => {
    listAnswers([note("a", "2026-10-02T08:30:00Z")], "Q1_-x");
    await open();
    const pages = screen.getByRole("navigation", { name: "More notifications" });
    expect(within(pages).getAllByRole("link").map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Older notifications", "/notifications?cursor=Q1_-x"],
    ]);
    cleanup();

    listAnswers([note("z", "2026-09-20T08:30:00Z")]);
    await open({ cursor: "Q1_-x" });
    expect(api.list).toHaveBeenLastCalledWith("/api/me/notifications", expect.objectContaining({ params: { query: { cursor: "Q1_-x" } } }));
    const back = screen.getByRole("navigation", { name: "More notifications" });
    expect(within(back).getAllByRole("link").map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Newest notifications", "/notifications"],
    ]);
  });

  it("drops a cursor that is not the API's and asks for the first page", async () => {
    listAnswers([note("a", "2026-10-02T08:30:00Z")]);
    await open({ cursor: "../../etc" });
    expect(api.list).toHaveBeenLastCalledWith("/api/me/notifications", expect.objectContaining({ params: { query: {} } }));
  });

  it("answers a stale cursor with one sentence and the way back to the newest", async () => {
    listAnswers([], null, 400);
    await open({ cursor: "old" });
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(empty.textContent).toContain("That page of notifications is no longer available.");
    expect(within(empty).getByRole("link", { name: "Newest notifications" }).getAttribute("href")).toBe("/notifications");
  });

  it("sends an ended session to the login page", async () => {
    listAnswers([], null, 401);
    await expect(NotificationsPage({ searchParams: Promise.resolve({}) } as never)).rejects.toThrow("redirect:/login");
  });
});
