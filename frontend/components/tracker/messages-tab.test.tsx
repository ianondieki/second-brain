import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { message, thread } from "@/test/messages";
import { resolveServerTree } from "@/test/server-tree";

import type { Me } from "@/lib/auth/routing";

import type { ThreadRead } from "./data";
import { EngagementScreen, type Tab } from "./EngagementScreen";
import { MessagesScreen } from "./MessagesScreen";
import type { Detail } from "./model";
import { messageHref, messagesHref } from "./TrackerFrame";

// REQ-ENG-11, AC-TRACK-9 (docs/spec/07 items 1, 2 and 4: Tracker · Documents · Messages · History): the Messages tab is
// its own route on both sides, landing on the thread's heading; the tab bar's unread count (a figure from 640 px, a dot
// below, words for screen readers); the not-open state (one sentence, one action), an engagement that ended before
// the thread opened, a refused read, the readable thread after the end; Send the route's one primary action, and the
// turn card's way to its buttons only when the next step is the viewer's.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const read = vi.hoisted(() => ({ current: { kind: "notOpen" } as ThreadRead }));
vi.mock("./data", () => ({
  engagementThread: async () => read.current,
  tier2ShareState: async () => null,
  engagementHistory: async () => ({ engagement_id: "e", chain_verified: true, events: [], endorsements: [], messages: [] }),
  orgMembers: async () => [],
  engagementDocument: async () => null,
}));

const ME = { user: { id: "u-dev" }, mfa: { enrolled: true } } as unknown as Me;
const ID = "0199b000-0000-7000-8000-00000000e001";

beforeEach(() => {
  read.current = { kind: "notOpen" };
});
afterEach(cleanup);

async function screenOf(d: Detail, tab: Tab) {
  return renderWithIntl(
    <>{await resolveServerTree(<EngagementScreen detail={d} me={ME} tab={tab} doc={null} basePath="/dev/engagements" />)}</>,
  );
}

async function messagesOf(d: Detail, basePath = "/dev/engagements", query = "") {
  return renderWithIntl(<>{await resolveServerTree(<MessagesScreen detail={d} basePath={basePath} query={query} />)}</>);
}

const confirmed = (overrides: Partial<Detail> = {}) =>
  detail({ state: "INTEREST_CONFIRMED", stage_group: "contact_nda", actions: ["withdraw"], ...overrides });
const orgTurn = (overrides: Partial<Detail> = {}) =>
  confirmed({ my_party: "org", actions: ["mark_contacted"], awaiting: [{ command: "mark_contacted", party: "org" }], whose_turn: ["org"], ...overrides });

describe("the Messages route's address", () => {
  it("lands on the thread's heading, for both portals, with and without ?org=, the id encoded", () => {
    expect(messagesHref("/dev/engagements", ID)).toBe(`/dev/engagements/${ID}/messages#messages-heading`);
    expect(messagesHref("/org/engagements", ID)).toBe(`/org/engagements/${ID}/messages#messages-heading`);
    expect(messagesHref("/org/engagements", ID, "?org=o1")).toBe(`/org/engagements/${ID}/messages?org=o1#messages-heading`);
    expect(messagesHref("/dev/engagements", "a/b c")).toBe("/dev/engagements/a%2Fb%20c/messages#messages-heading");
    expect(messageHref("/org/engagements", ID, "?org=o1", "m1")).toBe(`/org/engagements/${ID}/messages?org=o1#message-m1`);
  });
});

describe("the tab bar", () => {
  it("puts Messages between Documents and History, linking to the thread, with the unread count", async () => {
    await screenOf(confirmed({ unread_messages: 3 }), "tracker");
    const nav = screen.getByRole("navigation", { name: "Engagement sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `/dev/engagements/${ID}`,
      `/dev/engagements/${ID}?tab=documents`,
      `/dev/engagements/${ID}/messages#messages-heading`,
      `/dev/engagements/${ID}?tab=history`,
    ]);
    const messages = links[2];
    // A figure from 640 px, a dot below it (the strip fits 360 px), the words for screen readers.
    const figure = messages.querySelector<HTMLElement>("[data-unread='3'][aria-hidden='true']")!;
    expect(figure.textContent).toBe("3");
    expect(figure.className).toContain("hidden");
    expect(figure.className).toContain("sm:inline-grid");
    expect(messages.querySelector("[data-unread-dot][aria-hidden='true']")?.className).toContain("sm:hidden");
    expect(messages.querySelector(".sr-only")?.textContent).toBe("3 unread messages");
  });

  it("shows no count without unread messages, nor on the Messages route", async () => {
    await screenOf(confirmed({ unread_messages: 0 }), "tracker");
    expect(document.querySelector("[data-unread], [data-unread-dot]")).toBeNull();
    cleanup();
    read.current = { kind: "open", thread: thread() };
    await messagesOf(confirmed({ unread_messages: 2 }));
    expect(document.querySelector("[data-unread], [data-unread-dot]")).toBeNull();
    expect(screen.getByRole("link", { name: "Messages" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps the turn card's primary action on the tracker's own tabs", async () => {
    await screenOf(confirmed({ actions: ["send_nda", "withdraw"], awaiting: [{ command: "send_nda", party: "developer" }], whose_turn: ["developer"] }), "tracker");
    expect(document.querySelector("[data-primary]")?.textContent).toBe("Send the mutual NDA");
  });
});

describe("the Messages route", () => {
  it("has Send as its one primary action and, on the viewer's turn, a way to the Tracker tab", async () => {
    read.current = { kind: "open", thread: thread({ items: [message()] }) };
    await messagesOf(orgTurn(), "/org/engagements", "?org=o1");
    const primaries = document.querySelectorAll("[data-primary]");
    expect(primaries).toHaveLength(1);
    expect(primaries[0].textContent).toBe("Send");
    expect(document.querySelector("[data-actions]")).toBeNull();
    const toTracker = document.querySelector("[data-to-tracker]")!;
    expect(toTracker.textContent).toBe("Open the Tracker tab");
    expect(toTracker.getAttribute("href")).toBe(`/org/engagements/${ID}?org=o1`);
    expect(screen.getByRole("link", { name: "History" }).getAttribute("href")).toBe(`/org/engagements/${ID}?org=o1&tab=history`);
  });

  it("offers no way to the buttons when the next step is the other side's", async () => {
    read.current = { kind: "open", thread: thread() };
    await messagesOf(confirmed({ whose_turn: ["org"], awaiting: [{ command: "mark_contacted", party: "org" }] }));
    expect(document.querySelector("[data-to-tracker]")).toBeNull();
  });

  it("lands on the thread's heading, which takes focus and clears the top of the page", async () => {
    read.current = { kind: "open", thread: thread() };
    await messagesOf(confirmed());
    const heading = document.getElementById("messages-heading")!;
    expect(heading.tagName).toBe("H2");
    expect(heading.getAttribute("tabindex")).toBe("-1");
    expect(heading.closest("section")?.className).toContain("[&_h2]:scroll-mt-6");
  });
});

describe("before the thread opens (AC-TRACK-9)", () => {
  it("tells the developer when it opens, with the one action to the Tracker tab", async () => {
    await messagesOf(detail());
    const closed = document.querySelector("[data-thread-closed='not_open']")!;
    expect(closed.querySelector("p")?.textContent).toBe("Messages open when Telco A (fixture) approves to proceed, a non-binding step.");
    const links = closed.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].textContent).toBe("Open the Tracker tab");
    expect(links[0].getAttribute("href")).toBe(`/dev/engagements/${ID}`);
    expect(document.querySelector("[data-thread], textarea, [data-primary]")).toBeNull();
  });

  it("tells the organisation the same about its own step", async () => {
    await messagesOf(detail({ my_party: "org", my_roles: ["reviewer"] }), "/org/engagements");
    expect(document.querySelector("[data-thread-closed='not_open'] p")?.textContent).toBe(
      "Messages open when your organisation approves to proceed, a non-binding step.",
    );
  });

  it("says an engagement ended before the thread opened, not that it will open", async () => {
    await messagesOf(detail({ my_party: "org", state: "DECLINED", stage_group: null, due: null, whose_turn: [], awaiting: [] }), "/org/engagements");
    expect(document.querySelector("[data-thread-closed='ended'] p")?.textContent).toBe(
      "This engagement ended before messages opened, so there is no thread.",
    );
    expect(document.body.textContent).not.toContain("Messages open when");
  });

  it("says a refused read as the tracker does", async () => {
    read.current = { kind: "refused", refusal: "notFound" };
    await messagesOf(confirmed());
    expect(document.querySelector("[data-refusal='notFound'] p")?.textContent).toBe(
      "This engagement does not exist, or you are not one of its parties.",
    );
  });
});

describe("once open", () => {
  it("names the other side in its lead and offers the composer", async () => {
    read.current = { kind: "open", thread: thread() };
    await messagesOf(confirmed({ my_party: "org", my_roles: ["reviewer"] }), "/org/engagements");
    expect(document.body.textContent).toContain("Write to Achieng Otieno about this engagement.");
    expect(document.querySelector("[data-thread-empty]")?.textContent).toBe("No messages yet: write the first one below.");
    expect(screen.getByLabelText("Your message")).toBeTruthy();
  });

  it("keeps an ended engagement's thread readable and says why the composer is gone", async () => {
    read.current = { kind: "open", thread: thread({ status: "read_only", can_post: false, items: [message()] }) };
    await messagesOf(detail({ state: "WITHDRAWN", stage_group: null, due: null }));
    expect(document.querySelector("[data-message]")).toBeTruthy();
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelector("[data-thread-closed='read_only']")?.textContent).toBe(
      "This engagement has ended, so the thread stays here to read and no new messages can be sent.",
    );
  });

  it("says an empty ended thread in one sentence", async () => {
    read.current = { kind: "open", thread: thread({ status: "read_only", can_post: false }) };
    await messagesOf(detail({ state: "WITHDRAWN", stage_group: null, due: null }));
    expect(document.querySelector("[data-thread-empty]")).toBeNull();
    expect(document.querySelectorAll("[data-thread-closed]")).toHaveLength(1);
  });

  it("tells a member whose role only reads that there are no messages yet, and why there is no composer", async () => {
    read.current = { kind: "open", thread: thread({ can_post: false }) };
    await messagesOf(confirmed({ my_party: "org", my_roles: [] }), "/org/engagements");
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelector("[data-thread-empty]")?.textContent).toBe("No messages yet.");
    expect(document.querySelector("[data-thread-closed='viewer']")?.textContent).toBe("Your role lets you read this thread but not write in it.");
  });
});
