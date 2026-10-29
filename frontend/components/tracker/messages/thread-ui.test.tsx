import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import { message, thread } from "@/test/messages";
import { ENGAGEMENT_ID } from "@/test/engagement";

import type { UploadOptions } from "./calls";
import { Thread, type ThreadCalls, type ThreadProps } from "./Thread";
import type { Thread as ThreadPage } from "./thread";

// REQ-ENG-11 (AC-TRACK-9; docs/spec/06 6.9 "Messages tab", docs/spec/07 items 2, 4 and 6): the thread as the parties
// see it: messages by day with sender, side and time, plain text with its line breaks and never a link, own messages
// marked by words and place, the "New" line, earlier pages, files with their status and a download, a report of
// someone else's message, and the composer (Send the one primary action, a count near the limit, files that upload,
// scan and can be removed, a fixed sentence for every refusal).

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

beforeAll(() => {
  // jsdom has no <dialog> methods.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

function fakeCalls(overrides: Partial<ThreadCalls> = {}): ThreadCalls {
  return {
    postMessage: vi.fn<ThreadCalls["postMessage"]>(async (_id, body, ids) => ({
      ok: true,
      message: message({ id: "sent-1", body, mine: true, sender_party: "developer", sender_name: "Achieng Otieno", attachments: ids.map((id) => ({ id, file_name: "plan.md", content_type: "text/markdown", size_bytes: 45 })) }),
    })),
    olderPage: vi.fn<ThreadCalls["olderPage"]>(async () => ({ ok: true, thread: thread({ items: [message({ id: "older-1", body: "An older one", created_at: "2026-10-01T07:00:00Z" })] }) })),
    markRead: vi.fn<ThreadCalls["markRead"]>(async () => true),
    reportMessage: vi.fn<ThreadCalls["reportMessage"]>(async () => ({ ok: true, created: true })),
    fileLink: vi.fn<ThreadCalls["fileLink"]>(async () => ({ ok: true, url: "/api/file?sig=x" })),
    removeStaged: vi.fn<ThreadCalls["removeStaged"]>(async () => true),
    uploadFile: vi.fn<ThreadCalls["uploadFile"]>(async (_id, file, options: UploadOptions) => {
      options.onProgress?.(40);
      options.onProgress?.(100);
      return { ok: true, file: { id: `staged-${file.name}`, file_name: file.name, content_type: options.contentType, size_bytes: file.size, sha256: "00", av_status: "clean" } };
    }),
    ...overrides,
  };
}

function renderThread(initial: ThreadPage, calls: ThreadCalls = fakeCalls(), props: Partial<ThreadProps> = {}) {
  const view = renderWithIntl(
    <Thread
      engagementId={ENGAGEMENT_ID}
      initial={initial}
      today="2026-10-05"
      locale="en"
      orgName="Telco A (fixture)"
      empty="No messages yet: write the first one below."
      calls={calls}
      {...props}
    />,
  );
  return { ...view, calls };
}

const theirs = message({ id: "m-theirs", body: "Habari Achieng,\nSee https://example.com/plan for the pilot." });
const mine = message({
  id: "m-mine",
  mine: true,
  sender_party: "developer",
  sender_name: "Achieng Otieno",
  body: "Thank you, attached.",
  created_at: "2026-10-05T08:00:00Z",
  attachments: [{ id: "f-1", file_name: "pilot-plan.pdf", content_type: "application/pdf", size_bytes: 820_000 }],
});

describe("the thread", () => {
  it("shows each message's sender, side and time, its text as typed (never a link), and marks the caller's own", () => {
    renderThread(thread({ items: [theirs, mine] }));
    expect(screen.getByRole("heading", { level: 3, name: "Today" })).toBeTruthy();
    const other = document.querySelector<HTMLElement>("[data-message='m-theirs']")!;
    expect(other.getAttribute("data-mine")).toBe("false");
    expect(other.textContent).toContain("Rita Wanjiru");
    expect(other.textContent).toContain("Telco A (fixture)");
    expect(other.querySelector("time")?.textContent).toBe("10:05");
    const body = other.querySelector<HTMLElement>("[data-body]")!;
    expect(body.textContent).toBe("Habari Achieng,\nSee https://example.com/plan for the pilot.");
    expect(body.className).toContain("whitespace-pre-wrap");
    expect(other.querySelector("a")).toBeNull();
    const own = document.querySelector<HTMLElement>("[data-message='m-mine']")!;
    expect(own.getAttribute("data-mine")).toBe("true");
    expect(own.textContent).toContain("You");
    expect(own.className).toContain("justify-end");
    // A report is offered on someone else's message only.
    expect(within(other).getByRole("button", { name: "Report" })).toBeTruthy();
    expect(within(own).queryByRole("button", { name: "Report" })).toBeNull();
  });

  it("renders markup in a message as the text it is: no element made, no link, line breaks kept", () => {
    const raw = "<img src=x onerror=alert(1)><b>hi</b> https://x.example\nsecond line";
    renderThread(thread({ items: [message({ id: "m-markup", body: raw })] }));
    const body = document.querySelector<HTMLElement>("[data-message='m-markup'] [data-body]")!;
    expect(body.textContent).toBe(raw);
    expect(body.querySelector("img, b, a")).toBeNull();
    expect(body.children).toHaveLength(0);
    expect(body.className).toContain("whitespace-pre-wrap");
    expect(body.textContent?.split("\n")).toEqual(["<img src=x onerror=alert(1)><b>hi</b> https://x.example", "second line"]);
  });

  it("lists a sent file with its size and status, and opens it through a signed link", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const { calls } = renderThread(thread({ items: [mine] }));
    const file = document.querySelector<HTMLElement>("[data-file='f-1']")!;
    expect(file.textContent).toContain("pilot-plan.pdf");
    expect(file.textContent).toContain("820 kB");
    expect(file.querySelector("[data-file-status='ready']")?.textContent).toBe("Ready");
    fireEvent.click(within(file).getByRole("button", { name: "Download" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/api/file?sig=x"));
    expect(calls.fileLink).toHaveBeenCalledWith(ENGAGEMENT_ID, "m-mine", "f-1");
    vi.unstubAllGlobals();
  });

  it("marks the thread read up to its newest message, with a New line above the first unread", async () => {
    const { calls } = renderThread(
      thread({ items: [message({ id: "seen", created_at: "2026-10-05T06:00:00Z" }), theirs], unread: 1, last_read_at: "2026-10-05T06:30:00Z" }),
    );
    await waitFor(() => expect(calls.markRead).toHaveBeenCalledWith(ENGAGEMENT_ID, "m-theirs"));
    const divider = document.querySelector("[data-new-divider]")!;
    expect(divider.textContent).toBe("New");
    expect(divider.closest("li")?.querySelector("[data-message]")?.getAttribute("data-message")).toBe("m-theirs");
  });

  it("leaves the read marker alone when nothing is unread", async () => {
    const { calls } = renderThread(thread({ items: [theirs] }));
    await act(async () => {});
    expect(calls.markRead).not.toHaveBeenCalled();
  });

  it("loads earlier messages above, then the button goes and focus moves to the oldest", async () => {
    const { calls } = renderThread(thread({ items: [theirs], next_cursor: "c1" }));
    fireEvent.click(screen.getByRole("button", { name: "Load earlier messages" }));
    await waitFor(() => expect(document.querySelectorAll("[data-message]")).toHaveLength(2));
    expect(calls.olderPage).toHaveBeenCalledWith(ENGAGEMENT_ID, "c1");
    expect([...document.querySelectorAll("[data-message]")].map((m) => m.getAttribute("data-message"))).toEqual(["older-1", "m-theirs"]);
    expect(screen.queryByRole("button", { name: "Load earlier messages" })).toBeNull();
    await waitFor(() => expect(document.activeElement?.getAttribute("data-message")).toBe("older-1"));
  });

  it("says an empty thread in one sentence", () => {
    renderThread(thread());
    expect(document.querySelector("[data-thread-empty]")?.textContent).toBe("No messages yet: write the first one below.");
  });
});

describe("reporting a message", () => {
  it("asks for at least one reason, sends the chosen ones, and says what happens next", async () => {
    const { calls } = renderThread(thread({ items: [theirs] }));
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    // The sheet's code loads on the first press, then it opens as a modal.
    const sheet = await waitFor(() => {
      const found = document.querySelector("dialog[open]");
      expect(found).not.toBeNull();
      return found as HTMLDialogElement;
    });
    expect(sheet.querySelectorAll("input[type=checkbox]")).toHaveLength(5);
    fireEvent.click(within(sheet).getByRole("button", { name: "Send the report" }));
    expect(sheet.textContent).toContain("Choose at least one reason.");
    expect(calls.reportMessage).not.toHaveBeenCalled();
    fireEvent.click(within(sheet).getByLabelText("Spam"));
    fireEvent.click(within(sheet).getByLabelText("Shares contact details too early"));
    fireEvent.click(within(sheet).getByRole("button", { name: "Send the report" }));
    await waitFor(() => expect(calls.reportMessage).toHaveBeenCalledWith(ENGAGEMENT_ID, "m-theirs", ["spam", "contact_details"]));
    const said = await screen.findByText("Reported. A moderator will review this message; it stays in the thread meanwhile.");
    expect(said.closest("[role=status]")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Report" })).toBeNull();
  });

  it("says a second report of the same message is the one already filed", async () => {
    renderThread(thread({ items: [theirs] }), fakeCalls({ reportMessage: vi.fn(async () => ({ ok: true as const, created: false })) }));
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    const sheet = await waitFor(() => {
      const found = document.querySelector("dialog[open]");
      expect(found).not.toBeNull();
      return found as HTMLDialogElement;
    });
    fireEvent.click(within(sheet).getByLabelText("Spam"));
    fireEvent.click(within(sheet).getByRole("button", { name: "Send the report" }));
    const said = await screen.findByText("You already reported this message. A moderator will review it.");
    expect(said.closest("[data-reported='reportedAgain']")).toBeTruthy();
  });

  it("says a refusal inside the sheet", async () => {
    renderThread(thread({ items: [theirs] }), fakeCalls({ reportMessage: vi.fn(async () => ({ ok: false as const, refusal: "reportLimit" as const })) }));
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    const sheet = await waitFor(() => {
      const found = document.querySelector("dialog[open]");
      expect(found).not.toBeNull();
      return found as HTMLDialogElement;
    });
    fireEvent.click(within(sheet).getByLabelText("Abusive or threatening"));
    fireEvent.click(within(sheet).getByRole("button", { name: "Send the report" }));
    await waitFor(() => expect(sheet.textContent).toContain("You have reported the most messages allowed in a day. Try again tomorrow."));
    expect(sheet.hasAttribute("open")).toBe(true);
  });
});

describe("the composer in the thread", () => {
  it("adds a sent message at the end of the thread", async () => {
    const { calls } = renderThread(thread({ items: [theirs] }));
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Line one\nLine two" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.postMessage).toHaveBeenCalledWith(ENGAGEMENT_ID, "Line one\nLine two", []));
    await waitFor(() => expect(document.querySelector("[data-message='sent-1']")).toBeTruthy());
    const ids = [...document.querySelectorAll("[data-message]")].map((m) => m.getAttribute("data-message"));
    expect(ids).toEqual(["m-theirs", "sent-1"]);
    expect(document.querySelector("[data-message='sent-1'] [data-body]")?.textContent).toBe("Line one\nLine two");
  });

  it("is not there when the caller cannot post", () => {
    renderThread(thread({ items: [theirs], can_post: false, status: "read_only" }));
    expect(document.querySelector("[data-composer]")).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(document.querySelector("[data-message='m-theirs']")).toBeTruthy();
  });
});
