import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ENGAGEMENT_ID } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { LIMITS, message } from "@/test/messages";

import type { ThreadCalls, UploadOptions } from "./calls";
import { Composer } from "./Composer";
import type { Limits } from "./thread";

// REQ-ENG-11 (docs/spec/06 6.9 "Messages tab", docs/spec/07 items 2 and 6): the composer. Send is the tab's one
// primary action; a count shows near the limit; chosen files upload, are scanned and show Ready or Blocked, and can be
// removed before sending; every refusal is a fixed sentence: about the text on the text box (contains_contact says the
// contact step comes first), the rest above the buttons.

afterEach(cleanup);

function fakeCalls(overrides: Partial<ThreadCalls> = {}): ThreadCalls {
  return {
    postMessage: vi.fn<ThreadCalls["postMessage"]>(async (_id, body) => ({
      ok: true,
      message: message({ id: "sent-1", body, mine: true, sender_party: "developer", sender_name: "Achieng Otieno" }),
    })),
    olderPage: vi.fn(),
    markRead: vi.fn(),
    reportMessage: vi.fn(),
    fileLink: vi.fn(),
    removeStaged: vi.fn<ThreadCalls["removeStaged"]>(async () => true),
    uploadFile: vi.fn<ThreadCalls["uploadFile"]>(async (_id, file, options: UploadOptions) => {
      options.onProgress?.(40);
      options.onProgress?.(100);
      return { ok: true, file: { id: `staged-${file.name}`, file_name: file.name, content_type: options.contentType, size_bytes: file.size, sha256: "00", av_status: "clean" } };
    }),
    ...overrides,
  };
}

function renderComposer(limits: Limits = LIMITS, calls: ThreadCalls = fakeCalls()) {
  const sent = vi.fn();
  const closed = vi.fn();
  const view = renderWithIntl(
    <Composer engagementId={ENGAGEMENT_ID} limits={limits} locale="en" calls={calls} onSent={sent} onClosed={closed} />,
  );
  return { ...view, calls, sent, closed };
}

describe("the composer", () => {
  it("has Send as the one primary action, refuses a blank message on the text box, and sends the text", async () => {
    const { calls, sent } = renderComposer();
    const send = screen.getByRole("button", { name: "Send" });
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(send.hasAttribute("data-primary")).toBe(true);
    fireEvent.click(send);
    const box = screen.getByLabelText("Your message");
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById("message-body-error")?.textContent).toBe("Write a message first.");
    fireEvent.change(box, { target: { value: "Line one\nLine two" } });
    fireEvent.click(send);
    await waitFor(() => expect(calls.postMessage).toHaveBeenCalledWith(ENGAGEMENT_ID, "Line one\nLine two", []));
    await waitFor(() => expect(sent).toHaveBeenCalledWith(expect.objectContaining({ id: "sent-1" })));
    expect((box as HTMLTextAreaElement).value).toBe("");
    expect(document.querySelector("[data-composer-said]")?.textContent).toBe("Message sent.");
  });

  it("explains a refused contact detail on the text box (the contact step comes first)", async () => {
    renderComposer(LIMITS, fakeCalls({ postMessage: vi.fn(async () => ({ ok: false as const, refusal: "containsContact" as const })) }));
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Call me on 0712 345 678" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(document.getElementById("message-body-error")?.textContent).toContain(
        "before first contact is made, contact details are shared only through the tracker's contact step",
      ),
    );
  });

  it("says a closed thread above the buttons and has the page read again", async () => {
    const { closed } = renderComposer(LIMITS, fakeCalls({ postMessage: vi.fn(async () => ({ ok: false as const, refusal: "readOnly" as const })) }));
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("This engagement has ended, so no new messages can be sent.")).toBeTruthy();
    expect(closed).toHaveBeenCalled();
  });

  it("says when a limit lifts", async () => {
    renderComposer(LIMITS, fakeCalls({ postMessage: vi.fn(async () => ({ ok: false as const, refusal: "tooMany" as const, minutes: 12 })) }));
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("You have sent many messages here in the last hour. Try again in 12 minutes.")).toBeTruthy();
  });

  it("counts characters near the limit and refuses a message over it", () => {
    renderComposer({ ...LIMITS, max_chars: 500 });
    const box = screen.getByLabelText("Your message");
    fireEvent.change(box, { target: { value: "x".repeat(50) } });
    expect(document.querySelector("[data-meter]")).toBeNull();
    fireEvent.change(box, { target: { value: "x".repeat(120) } });
    expect(document.querySelector("[data-meter]")?.textContent).toBe("Characters left: 380");
    fireEvent.change(box, { target: { value: "x".repeat(503) } });
    expect(document.querySelector("[data-meter='over']")?.textContent).toBe("Characters over the limit: 3");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(document.getElementById("message-body-error")?.textContent).toBe("Shorten your message to 500 characters or fewer.");
  });

  it("uploads chosen files, shows each one's status, and sends the ready ones", async () => {
    const { calls } = renderComposer();
    const picker = document.querySelector<HTMLInputElement>("input[type=file]")!;
    expect(picker.multiple).toBe(true);
    const plan = new File(["# Plan"], "plan.md", { type: "" });
    const deck = new File(["x"], "deck.pptx", { type: "application/vnd.ms-powerpoint" });
    fireEvent.change(picker, { target: { files: [plan, deck] } });
    await waitFor(() => expect(document.querySelector("[data-pending-file='plan.md']")?.getAttribute("data-status")).toBe("ready"));
    expect(calls.uploadFile).toHaveBeenCalledTimes(1);
    expect(vi.mocked(calls.uploadFile).mock.calls[0][2].contentType).toBe("text/markdown");
    const blocked = document.querySelector<HTMLElement>("[data-pending-file='deck.pptx']")!;
    expect(blocked.getAttribute("data-status")).toBe("blocked");
    expect(blocked.textContent).toContain("Blocked");
    expect(blocked.textContent).toContain("This kind of file cannot be sent.");
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "The plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Remove the blocked files before you send.")).toBeTruthy();
    expect(calls.postMessage).not.toHaveBeenCalled();
    fireEvent.click(within(blocked).getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(calls.postMessage).toHaveBeenCalledWith(ENGAGEMENT_ID, "The plan", ["staged-plan.md"]));
  });

  it("shows a file the scan refused as blocked, and removing it deletes its record", async () => {
    const { calls } = renderComposer(
      LIMITS,
      fakeCalls({ uploadFile: vi.fn(async () => ({ ok: false as const, problem: "infected" as const, attachmentId: "refused-1" })) }),
    );
    fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    const row = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-pending-file='notes.txt'][data-status='blocked']");
      expect(found).toBeTruthy();
      return found!;
    });
    expect(row.textContent).toContain("This file did not pass the malware scan, so it was not kept.");
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(calls.removeStaged).toHaveBeenCalledWith(ENGAGEMENT_ID, "refused-1");
    expect(document.querySelector("[data-pending-file]")).toBeNull();
  });

  it("waits for uploads before sending", async () => {
    let finish: () => void = () => {};
    const uploadFile = vi.fn<ThreadCalls["uploadFile"]>(
      (_id, file, options) =>
        new Promise((resolve) => {
          options.onProgress?.(30);
          finish = () => resolve({ ok: true, file: { id: "s", file_name: file.name, content_type: "application/pdf", size_bytes: 1, sha256: "0", av_status: "clean" } });
        }),
    );
    const { calls } = renderComposer(LIMITS, fakeCalls({ uploadFile }));
    fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [new File(["%PDF"], "a.pdf", { type: "application/pdf" })] } });
    const row = document.querySelector<HTMLElement>("[data-pending-file='a.pdf']")!;
    await waitFor(() => expect(row.textContent).toContain("Uploading 30%"));
    expect(within(row).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("30");
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Wait until every file shows Ready, or remove it.")).toBeTruthy();
    expect(calls.postMessage).not.toHaveBeenCalled();
    await act(async () => finish());
    await waitFor(() => expect(row.getAttribute("data-status")).toBe("ready"));
  });

});

