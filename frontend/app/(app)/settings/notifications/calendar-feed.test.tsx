import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

// P27 track A (REQ-ENG-13; D-70): Settings › Notifications › Calendar feed. Create shows the private link once in a
// read-only field with Copy and the two ways to subscribe; Make a new link asks first, in place, then replaces it (the
// old one stops working);
// Remove ends it; a live feed is not shown again (the API keeps only its hash); a failure says so; the organisation's
// feed is its own route.

const calls = vi.hoisted(() => ({
  list: [] as Array<{ method: string; path: string; params?: unknown }>,
  fail: false,
}));
vi.mock("@/lib/api/client", () => {
  const answer = (method: string) => async (path: string, init?: { params?: unknown }) => {
    calls.list.push({ method, path, params: init?.params });
    if (calls.fail) return { data: undefined, response: { ok: false, status: 500 } };
    if (method === "DELETE") return { data: undefined, response: { ok: true, status: 204 } };
    return {
      data: { url: `https://wazo.example/api/calendar/tok${calls.list.length}.ics` },
      response: { ok: true, status: 201 },
    };
  };
  return { api: { POST: answer("POST"), DELETE: answer("DELETE") } };
});

const { CalendarFeed, feedLinks } = await import("./CalendarFeed");

beforeEach(() => {
  calls.list = [];
  calls.fail = false;
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the calendar feed", () => {
  it("creates the link and shows it once, read-only, with Copy and the two ways to subscribe", async () => {
    renderWithIntl(<CalendarFeed initial="none" lastRead={null} />);
    expect(screen.getByText("You have no feed link yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create a feed link" }));
    const field = await screen.findByRole("textbox", { name: "Feed link" });
    expect(calls.list).toEqual([{ method: "POST", path: "/api/me/calendar-feed", params: undefined }]);
    // The new link takes the focus (selected, ready to copy).
    await waitFor(() => expect(document.activeElement).toBe(field));
    expect((field as HTMLInputElement).value).toBe("https://wazo.example/api/calendar/tok1.ics");
    expect(field.hasAttribute("readonly")).toBe(true);
    expect(field.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("Copy it now: it is shown only this once.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open in Apple Calendar" }).getAttribute("href")).toBe(
      "webcal://wazo.example/api/calendar/tok1.ics",
    );
    expect(screen.getByRole("link", { name: "Open in Google Calendar" }).getAttribute("href")).toBe(
      `https://calendar.google.com/calendar/render?cid=${encodeURIComponent("webcal://wazo.example/api/calendar/tok1.ics")}`,
    );
    // No primary action of its own: the page keeps its one.
    expect(document.querySelector("[data-primary]")).toBeNull();
  });

  it("copies the link and says so; where the clipboard is refused, selects it and says to copy it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderWithIntl(<CalendarFeed initial="none" lastRead={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Create a feed link" }));
    await screen.findByRole("textbox", { name: "Feed link" });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(writeText).toHaveBeenCalledWith("https://wazo.example/api/calendar/tok1.ics");
    expect(screen.getByRole("status").textContent).toBe("Copied");
    writeText.mockRejectedValueOnce(new Error("denied"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));
    expect(screen.getByRole("status").textContent).toBe("Select the link and copy it yourself.");
  });

  it("says a live feed is live (never its link), makes a new link, and removes it", async () => {
    renderWithIntl(<CalendarFeed initial="live" lastRead="12 Oct 2026, 14:05 EAT" />);
    expect(screen.getByText("Your feed is live. A calendar app last read it on 12 Oct 2026, 14:05 EAT.")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make a new link" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace the link" }));
    const field = await screen.findByRole("textbox", { name: "Feed link" });
    expect((field as HTMLInputElement).value).toContain("tok1");
    fireEvent.click(screen.getByRole("button", { name: "Remove the feed" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("The feed is removed. Its link no longer works."),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    // Focus moves to the button that took the pressed one's place, never back to the page's start.
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Create a feed link" })),
    );
    expect(calls.list.map((call) => call.method)).toEqual(["POST", "DELETE"]);
  });

  // P27 UX: a live subscription stops updating the moment its link is replaced, so the button asks first, in place
  // (no dialog): the question takes the focus; Keep (or Escape) changes nothing and goes back to the button.
  it("asks before making a new link, in place; keeping the link calls nothing", async () => {
    renderWithIntl(<CalendarFeed initial="live" lastRead={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Make a new link" }));
    const question = screen.getByRole("group", {
      name: "Replace the link? Calendars that use the current one stop updating.",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Make a new link" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(question));
    expect(document.querySelector("[data-primary]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keep the current link" }));
    expect(calls.list).toEqual([]);
    expect(screen.queryByRole("group")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Make a new link" })));
    // Escape keeps it too.
    fireEvent.click(screen.getByRole("button", { name: "Make a new link" }));
    fireEvent.keyDown(screen.getByRole("group"), { key: "Escape" });
    expect(screen.queryByRole("group")).toBeNull();
    expect(calls.list).toEqual([]);
  });

  it("keeps the link field at the controls' height on a phone (it grows beside Copy from 640 px only)", async () => {
    renderWithIntl(<CalendarFeed initial="none" lastRead={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Create a feed link" }));
    const field = await screen.findByRole("textbox", { name: "Feed link" });
    const classes = field.className.split(" ");
    expect(classes).toEqual(expect.arrayContaining(["h-12", "sm:flex-1"]));
    expect(classes).not.toContain("flex-1");
  });

  it("uses the organisation's own feed for a member", async () => {
    renderWithIntl(<CalendarFeed initial="live" orgId="org-1" lastRead={null} />);
    expect(screen.getByText("Your feed is live. No calendar app has read it yet.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Make a new link" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace the link" }));
    await screen.findByRole("textbox", { name: "Feed link" });
    expect(calls.list).toEqual([
      { method: "POST", path: "/api/orgs/{org_id}/calendar-feed", params: { path: { org_id: "org-1" } } },
    ]);
  });

  it("says when it did not work, and keeps the state it had", async () => {
    calls.fail = true;
    renderWithIntl(<CalendarFeed initial="live" lastRead={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove the feed" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("That did not work. Try again."));
    expect(screen.getByRole("button", { name: "Make a new link" })).toBeTruthy();
  });

  it("makes a relative link absolute against the site", () => {
    expect(feedLinks("/api/calendar/abc.ics", "http://localhost:3000").webcal).toBe(
      "webcal://localhost:3000/api/calendar/abc.ics",
    );
  });
});
