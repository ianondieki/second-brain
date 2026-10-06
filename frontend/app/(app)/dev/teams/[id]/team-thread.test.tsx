import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { toThreadPage, type TeamThread as TeamThreadRead } from "../teams";
import { TeamThread } from "./TeamThread";

// REQ-DEV-03 (P22-CF): the team thread's calls go to /api/me/teams/{thread_id} (never the engagement's endpoints):
// opening an unread thread marks it read, Send posts the message and draws it, a closed thread's refusal reads the
// page again.

const POST = vi.fn();
const GET = vi.fn();
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => POST(...args), GET: (...args: unknown[]) => GET(...args) } }));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  POST.mockReset();
  refresh.mockReset();
});

const ID = "01a11223-32cd-732d-9755-f7206d3c33e4";

function read(unread: number): TeamThreadRead {
  return {
    thread: {
      id: ID,
      counterpart: { user_id: "u2", handle: "dev-kb3dysnk", headline: null },
      problem: { id: "p1", title: "Tower sites go down" },
      created_at: "2026-10-06T10:00:00+03:00",
      last_message_at: "2026-10-06T12:00:00+03:00",
      unread,
      open: true,
      closed_at: null,
      closed_reason: null,
    },
    can_post: true,
    max_chars: 4000,
    last_read_at: null,
    items: [{ id: "m2", mine: false, body: "Happy to help.", redacted: false, created_at: "2026-10-06T12:00:00+03:00" }],
    next_cursor: null,
  };
}

function open(unread = 0) {
  renderWithIntl(
    <TeamThread threadId={ID} initial={toThreadPage(read(unread), "dev-kb3dysnk")} counterpart="dev-kb3dysnk" today="2026-10-06" locale="en" empty={null} person={null} ideas={[]} />,
  );
}

describe("the team thread's calls", () => {
  it("marks an unread thread read up to its newest message", async () => {
    POST.mockResolvedValue({ response: new Response(null, { status: 200 }) });
    open(1);
    await waitFor(() => expect(POST).toHaveBeenCalledWith("/api/me/teams/{thread_id}/read", { params: { path: { thread_id: ID } }, body: { up_to: "m2" } }));
  });

  it("Send posts to the team thread and draws the message as the caller's", async () => {
    POST.mockResolvedValue({
      data: { id: "m3", mine: true, body: "On it.", redacted: false, created_at: "2026-10-06T12:30:00+03:00" },
      error: undefined,
      response: new Response(null, { status: 201 }),
    });
    open();
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "On it." } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    await waitFor(() => expect(document.querySelector('[data-message="m3"]')).not.toBeNull());
    expect(POST).toHaveBeenCalledWith("/api/me/teams/{thread_id}/messages", { params: { path: { thread_id: ID } }, body: { body: "On it." } });
    expect(document.querySelector('[data-message="m3"]')?.getAttribute("data-mine")).toBe("true");
    expect(POST.mock.calls.some(([path]) => String(path).startsWith("/api/engagements"))).toBe(false);
  });

  it("a thread closed meanwhile says so as a thread, and the page is read again", async () => {
    POST.mockResolvedValue({ data: undefined, error: { detail: { code: "thread_closed" } }, response: new Response(null, { status: 409 }) });
    open();
    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Still there?" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send" })));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toBeTruthy();
  });
});
