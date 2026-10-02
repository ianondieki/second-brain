import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { MarkAllRead } from "./MarkAllRead";
import { ReadLink } from "./ReadLink";

// P19-C: opening a row marks it read, then navigates (so the bell on the next page counts it); "Mark all as read"
// marks every one, then reads the page and the bell again. Both writes are idempotent; neither blocks the person.

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const calls = vi.hoisted(() => ({ markRead: vi.fn<(id: string) => Promise<boolean>>(), markAllRead: vi.fn<() => Promise<boolean>>() }));
vi.mock("./calls", () => calls);

const LABELS = {
  idle: "Mark all as read",
  busy: "Marking as read…",
  done: "All your notifications are marked as read.",
  failed: "Nothing was marked as read; try again in a moment.",
};

beforeEach(() => {
  calls.markRead.mockResolvedValue(true);
  calls.markAllRead.mockResolvedValue(true);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function row(unread: boolean) {
  renderWithIntl(
    <main id="main">
      <h1>Notifications</h1>
      <ReadLink id="n1" href="/dev/engagements/e1" unread={unread}>
        Approved
      </ReadLink>
    </main>,
  );
  return screen.getByRole("link", { name: "Approved" });
}

describe("opening a row", () => {
  it("records an unread one as read first, then goes where it points", async () => {
    const link = row(true);
    expect(link.getAttribute("href")).toBe("/dev/engagements/e1");
    let finish: (ok: boolean) => void = () => undefined;
    calls.markRead.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    fireEvent.click(link);
    expect(calls.markRead).toHaveBeenCalledWith("n1");
    expect(router.push).not.toHaveBeenCalled(); // not before the read is recorded
    expect(link.getAttribute("aria-busy")).toBe("true");
    fireEvent.click(link); // a second press while opening changes nothing
    await act(async () => finish(true));
    expect(router.push).toHaveBeenCalledTimes(1);
    expect(router.push).toHaveBeenCalledWith("/dev/engagements/e1");
    expect(calls.markRead).toHaveBeenCalledTimes(1);
  });

  it("still goes there when the read could not be recorded", async () => {
    calls.markRead.mockResolvedValue(false);
    fireEvent.click(row(true));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/dev/engagements/e1"));
  });

  it("is a plain link for a read one: nothing is posted", () => {
    const link = row(false);
    const event = fireEvent.click(link);
    expect(calls.markRead).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled(); // next/link navigates it
    expect(event).toBe(true);
  });

  it("records it but leaves a new-tab press to the browser", () => {
    const link = row(true);
    const notCancelled = fireEvent.click(link, { ctrlKey: true });
    expect(calls.markRead).toHaveBeenCalledWith("n1");
    expect(notCancelled).toBe(true);
    expect(router.push).not.toHaveBeenCalled();
  });
});

describe("Mark all as read", () => {
  function renderAction(unread: number) {
    renderWithIntl(
      <main id="main">
        <h1>Notifications</h1>
        <MarkAllRead unread={unread} labels={LABELS} />
      </main>,
    );
    return screen.getByRole("button", { name: "Mark all as read" });
  }

  it("marks every one read, says so, moves focus to the title and refreshes the page and the bell", async () => {
    const button = renderAction(3);
    expect(button.hasAttribute("data-primary")).toBe(false); // the one secondary action
    fireEvent.click(button);
    await waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1));
    expect(calls.markAllRead).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe(LABELS.done);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
  });

  it("says a failure in words and stays there to try again", async () => {
    calls.markAllRead.mockResolvedValue(false);
    const button = renderAction(3);
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", LABELS.failed);
    expect(router.refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Mark all as read" })).toHaveProperty("disabled", false);
  });

  it("is disabled with nothing unread", () => {
    expect(renderAction(0)).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    expect(calls.markAllRead).not.toHaveBeenCalled();
  });
});
