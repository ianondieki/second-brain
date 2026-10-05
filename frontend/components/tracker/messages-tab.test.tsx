import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { message, thread } from "@/test/messages";
import { resolveServerTree } from "@/test/server-tree";

import type { Me } from "@/lib/auth/routing";

import type { ThreadRead } from "./data";
import { EngagementScreen, type Tab } from "./EngagementScreen";
import { preloadThread } from "./messages/MessagesThread";
import { MessagesTab } from "./MessagesTab";
import type { Detail } from "./model";

// REQ-ENG-11, AC-TRACK-9 (docs/spec/07 item 1: Tracker · Documents · Messages · History): the tracker's Messages tab
// on both sides: where it sits, its unread count (words for screen readers), the sentence before the thread opens
// (the organisation is refused until INTEREST_CONFIRMED; nothing else is shown), the readable thread after the end,
// and Send as the screen's one primary action while the composer is there.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

const read = vi.hoisted(() => ({ current: { open: false } as ThreadRead }));
vi.mock("./data", () => ({
  engagementThread: async () => read.current,
  tier2ShareState: async () => null,
  engagementHistory: async () => ({ engagement_id: "e", chain_verified: true, events: [], endorsements: [], messages: [] }),
  orgMembers: async () => [],
  engagementDocument: async () => null,
}));

const ME = { user: { id: "u-dev" }, mfa: { enrolled: true } } as unknown as Me;

beforeAll(async () => {
  await preloadThread();
});
beforeEach(() => {
  read.current = { open: false };
});
afterEach(cleanup);

async function screenOf(d: Detail, tab: Tab) {
  return renderWithIntl(
    <>{await resolveServerTree(<EngagementScreen detail={d} me={ME} tab={tab} doc={null} basePath="/dev/engagements" />)}</>,
  );
}

async function tabOf(d: Detail) {
  return renderWithIntl(<>{await resolveServerTree(<MessagesTab detail={d} read={read.current} />)}</>);
}

const confirmed = (overrides: Partial<Detail> = {}) =>
  detail({ state: "INTEREST_CONFIRMED", stage_group: "contact_nda", actions: ["withdraw"], ...overrides });

describe("the tab", () => {
  it("sits between Documents and History, with the unread count in words for screen readers", async () => {
    await screenOf(confirmed({ unread_messages: 3 }), "tracker");
    const nav = screen.getByRole("navigation", { name: "Engagement sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/dev/engagements/0199b000-0000-7000-8000-00000000e001",
      "/dev/engagements/0199b000-0000-7000-8000-00000000e001?tab=documents",
      "/dev/engagements/0199b000-0000-7000-8000-00000000e001?tab=messages",
      "/dev/engagements/0199b000-0000-7000-8000-00000000e001?tab=history",
    ]);
    const messages = links[2];
    expect(messages.querySelector("[data-unread='3'][aria-hidden='true']")?.textContent).toBe("3");
    expect(messages.querySelector(".sr-only")?.textContent).toBe("3 unread messages");
  });

  it("shows no count without unread messages, nor on the open Messages tab", async () => {
    await screenOf(confirmed({ unread_messages: 0 }), "tracker");
    expect(document.querySelector("[data-unread]")).toBeNull();
    cleanup();
    read.current = { open: true, thread: thread() };
    await screenOf(confirmed({ unread_messages: 2 }), "messages");
    expect(document.querySelector("[data-unread]")).toBeNull();
  });

  it("makes Send the screen's one primary action while the composer is there", async () => {
    read.current = { open: true, thread: thread({ items: [message()] }) };
    await screenOf(confirmed({ actions: ["send_nda", "withdraw"], awaiting: [{ command: "send_nda", party: "developer" }], whose_turn: ["developer"] }), "messages");
    const primaries = document.querySelectorAll("[data-primary]");
    expect(primaries).toHaveLength(1);
    expect(primaries[0].textContent).toBe("Send");
    // The turn card's next step is still there, as a secondary button.
    expect(within(document.querySelector<HTMLElement>("[data-actions]")!).getByRole("button", { name: "Send the mutual NDA" })).toBeTruthy();
  });

  it("keeps the turn card's primary action on the other tabs", async () => {
    await screenOf(confirmed({ actions: ["send_nda", "withdraw"], awaiting: [{ command: "send_nda", party: "developer" }], whose_turn: ["developer"] }), "tracker");
    expect(document.querySelector("[data-primary]")?.textContent).toBe("Send the mutual NDA");
  });
});

describe("before the thread opens (AC-TRACK-9)", () => {
  it("tells the developer, in one sentence, when it opens, and offers nothing else", async () => {
    await tabOf(detail());
    const closed = document.querySelector("[data-thread-closed='not_open']")!;
    expect(closed.textContent).toBe("Messages open when Telco A (fixture) approves to proceed, a non-binding step.");
    expect(document.querySelector("[data-thread]")).toBeNull();
    expect(document.querySelector("textarea, button, [data-primary]")).toBeNull();
  });

  it("tells the organisation the same about its own step", async () => {
    await tabOf(detail({ my_party: "org", my_roles: ["reviewer"] }));
    expect(document.querySelector("[data-thread-closed='not_open']")?.textContent).toBe(
      "Messages open when your organisation approves to proceed, a non-binding step.",
    );
    expect(document.querySelector("textarea")).toBeNull();
  });
});

describe("once open", () => {
  it("names the other side in its lead and offers the composer", async () => {
    read.current = { open: true, thread: thread() };
    await tabOf(confirmed({ my_party: "org", my_roles: ["reviewer"] }));
    expect(screen.getByRole("heading", { level: 2, name: "Messages" })).toBeTruthy();
    expect(document.body.textContent).toContain("Write to Achieng Otieno about this engagement.");
    expect(document.body.textContent).toContain("No messages yet: write the first one below.");
    expect(screen.getByLabelText("Your message")).toBeTruthy();
  });

  it("keeps an ended engagement's thread readable and says why the composer is gone", async () => {
    read.current = { open: true, thread: thread({ status: "read_only", can_post: false, items: [message()] }) };
    await tabOf(detail({ state: "WITHDRAWN", stage_group: null, due: null }));
    expect(document.querySelector("[data-message]")).toBeTruthy();
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelector("[data-thread-closed='read_only']")?.textContent).toBe(
      "This engagement has ended, so the thread stays here to read and no new messages can be sent.",
    );
  });

  it("says when a member's role reads but cannot write", async () => {
    read.current = { open: true, thread: thread({ can_post: false }) };
    await tabOf(confirmed({ my_party: "org", my_roles: [] }));
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelector("[data-thread-empty]")?.textContent).toBe("No messages were sent on this engagement.");
    expect(document.querySelector("[data-thread-closed='viewer']")?.textContent).toBe("Your role lets you read this thread but not write in it.");
  });
});
