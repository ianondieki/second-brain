import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { detail, history, summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { EngagementCard } from "./EngagementCard";
import { EngagementRow } from "./EngagementRow";
import { HistoryList, timeline } from "./HistoryList";
import { NeedsYouCard } from "./NeedsYouCard";

// REQ-ENG-11 (P21-A8; docs/spec/06 6.9): the History tab lists the thread's messages among the events, newest first
// ("Message from …", the side and the time; never the text), the same for both parties; the Engagements lists say how
// many messages are unread, as words beside a mark and never as a third chip (docs/spec/07 item 2).

afterEach(cleanup);

const messages = [
  { id: "msg-1", sender_party: "developer" as const, sender_name: "Achieng Otieno", created_at: "2026-09-23T12:00:00Z" },
  { id: "msg-2", sender_party: "org" as const, sender_name: "Rita Wanjiru", created_at: "2026-09-25T09:00:00Z" },
];

describe("the History tab", () => {
  it("puts the messages among the events by time, newest first", () => {
    const entries = timeline(history({ messages }));
    expect(entries.map((e) => (e.kind === "message" ? e.message.id : e.event.command))).toEqual([
      "msg-2",
      "start_review",
      "msg-1",
      "create",
    ]);
  });

  it("names each message's sender and side, never its text", () => {
    renderWithIntl(<HistoryList history={history({ messages })} />);
    const entries = [...document.querySelectorAll("[data-history-message]")];
    expect(entries.map((e) => e.getAttribute("data-history-message"))).toEqual(["org", "developer"]);
    expect(entries[0].querySelector("h3")?.textContent).toBe("Message from Rita Wanjiru");
    expect(entries[0].textContent).toContain("Organisation");
    expect(entries[0].querySelector("time")?.getAttribute("dateTime")).toBe("2026-09-25T09:00:00Z");
    expect(entries[1].querySelector("h3")?.textContent).toBe("Message from Achieng Otieno");
    expect(entries[1].textContent).toContain("Developer");
    // The events are still the [data-event] rows, in their order.
    expect([...document.querySelectorAll("[data-event]")].map((e) => e.getAttribute("data-event"))).toEqual(["start_review", "create"]);
  });

  it("links each message's entry to that message in the thread", () => {
    renderWithIntl(<HistoryList history={history({ messages })} messageLink={(id) => `/dev/engagements/e/messages#message-${id}`} />);
    const link = document.querySelector("[data-history-message='org'] h3 a")!;
    expect(link.textContent).toBe("Message from Rita Wanjiru");
    expect(link.getAttribute("href")).toBe("/dev/engagements/e/messages#message-msg-2");
    // A 44 px tap area (WCAG 2.5.8): padding taken back by a negative margin, the text unmoved.
    expect(link.className).toContain("py-2.5");
    expect(link.className).toContain("-my-2.5");
  });

  it("reads as before without messages", () => {
    renderWithIntl(<HistoryList history={history()} />);
    expect(document.querySelectorAll("[data-history-message]")).toHaveLength(0);
    expect(document.querySelectorAll("[data-event]")).toHaveLength(2);
  });
});

describe("the Engagements lists", () => {
  it("say how many messages are unread on a row, beside at most two chips", () => {
    renderWithIntl(<EngagementRow item={summary({ unread_messages: 2, whose_turn: ["developer"] })} mine="developer" href="/dev/engagements/e" />);
    const unread = document.querySelector("[data-unread-messages='2']")!;
    expect(unread.textContent).toBe("2 unread messages");
    expect(unread.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    expect(document.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
  });

  it("say one unread message in the singular, and nothing when none", () => {
    renderWithIntl(<EngagementRow item={summary({ unread_messages: 1 })} mine="org" href="/org/engagements/e" />);
    expect(document.querySelector("[data-unread-messages]")?.textContent).toBe("1 unread message");
    cleanup();
    renderWithIntl(<EngagementRow item={summary({ unread_messages: 0 })} mine="org" href="/org/engagements/e" />);
    expect(document.querySelector("[data-unread-messages]")).toBeNull();
  });

  it("say it on the Needs-you card and the compact card too", () => {
    renderWithIntl(
      <NeedsYouCard item={detail({ unread_messages: 4, whose_turn: ["developer"] })} mine="developer" href="/dev/engagements/e" action="Open the tracker" />,
    );
    expect(document.querySelector("[data-unread-messages]")?.textContent).toBe("4 unread messages");
    cleanup();
    renderWithIntl(<EngagementCard item={summary({ unread_messages: 3 })} mine="org" href="/org/engagements/e" />);
    expect(document.querySelector("[data-unread-messages]")?.textContent).toBe("3 unread messages");
  });
});
