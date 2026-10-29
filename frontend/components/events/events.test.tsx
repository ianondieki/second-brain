import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { EventCalls } from "./calls";
import { CancelEvent } from "./CancelEvent";
import { checkEvent, EMPTY_EVENT, eventBody, eventRefusalOf, nairobiIso, type EventOut } from "./event-draft";
import { EventForm } from "./EventForm";
import { cancellable, EVENT_CHIP } from "./status";

// REQ-DEV-02 (P22-BF; D-60): the event form shared by an organisation's "Post an event" and the staff's "Post a
// platform event": its checks, the body (Nairobi times with their offset), the Online switch swapping the venue and
// county for the join address, the API's 422 under each field, the refusals in words, and Cancel behind a dialog.

const router = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => {
  router.push.mockReset();
  router.refresh.mockReset();
});
afterEach(cleanup);

const EVENT_ID = "01a11043-1017-70dc-b565-dfbe1df95846";

function eventOut(overrides: Partial<EventOut> = {}): EventOut {
  return {
    id: EVENT_ID,
    org_id: "01a0ee62-0000-7000-8000-00000000000b",
    organiser: "Telco A",
    title: "Meetup",
    description: "Talks.",
    starts_at: "2026-11-22T18:00:00+03:00",
    ends_at: "2026-11-22T20:30:00+03:00",
    online: false,
    venue: "Hub",
    county_code: "KE-30",
    county_name: "Nairobi City",
    join_url: null,
    link: null,
    status: "draft",
    decided_at: null,
    cancelled_at: null,
    created_at: "2026-11-20T10:00:00+03:00",
    updated_at: "2026-11-20T10:00:00.123456+03:00",
    ...overrides,
  };
}

function calls(overrides: Partial<EventCalls> = {}): EventCalls {
  return {
    post: vi.fn(async () => ({ ok: true as const, value: eventOut() })),
    cancel: vi.fn(async () => ({ ok: true as const, value: eventOut({ status: "cancelled" }) })),
    ...overrides,
  };
}

function renderForm(api: EventCalls) {
  renderWithIntl(
    <EventForm
      counties={[{ id: "KE-30", label: "Nairobi City" }]}
      poster="Telco A"
      target={{ kind: "org", orgId: "o1" }}
      doneBase="/org/events"
      doneQuery="?org=o1"
      cancelHref="/org/events"
      calls={api}
    />,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: false, selector: "input, textarea, select" }), { target: { value } });
}

describe("the event draft's rules", () => {
  it("sends Nairobi times with their offset, and an online event without a place", () => {
    expect(nairobiIso("2026-11-22", "18:00")).toBe("2026-11-22T18:00:00+03:00");
    expect(nairobiIso("2026-11-22", "")).toBeNull();
    const draft = {
      ...EMPTY_EVENT,
      title: " Clinic ",
      description: "Talks",
      startDate: "2026-11-24",
      startTime: "10:00",
      endDate: "2026-11-24",
      endTime: "11:30",
      online: true,
      venue: "left over",
      county: "KE-30",
      joinUrl: "https://meet.example/x",
    };
    expect(checkEvent(draft)).toEqual({});
    expect(eventBody(draft)).toEqual({
      title: "Clinic",
      description: "Talks",
      starts_at: "2026-11-24T10:00:00+03:00",
      ends_at: "2026-11-24T11:30:00+03:00",
      online: true,
      venue: null,
      county_code: null,
      join_url: "https://meet.example/x",
      link: null,
    });
  });

  it("checks the end, the span, the place and the addresses", () => {
    const base = { ...EMPTY_EVENT, title: "T", description: "D", startDate: "2026-11-24", startTime: "10:00", endTime: "09:00" };
    expect(checkEvent({ ...base, endDate: "2026-11-24" }).endDate).toBe("end_before_start");
    expect(checkEvent({ ...base, endDate: "2026-11-28" }).endDate).toBe("span_too_long");
    const atVenue = checkEvent({ ...base, endDate: "2026-11-25" });
    expect(atVenue).toEqual({ venue: "venue_required", county: "county_required" });
    expect(checkEvent({ ...base, endDate: "2026-11-25", online: true, joinUrl: "http://x.example" }).joinUrl).toBe("invalid_url");
    expect(checkEvent({ ...base, endDate: "2026-11-25", online: true, joinUrl: "https://x.example", link: "ftp://x" }).link).toBe(
      "invalid_url",
    );
    expect(checkEvent({ ...base, title: "x".repeat(121), endDate: "2026-11-25", online: true, joinUrl: "https://x.example" }).title).toBe(
      "too_long",
    );
  });

  it("words the API's refusals by code, with a 422's fields", () => {
    const invalid = eventRefusalOf(422, {
      detail: {
        code: "invalid_event",
        message: "x",
        errors: [
          { field: "starts_at", code: "start_past", message: "x" },
          { field: "county_code", code: "unknown_county", message: "x" },
          { field: "venue", code: "something_new", message: "x" },
        ],
      },
    });
    expect(invalid).toEqual({
      ok: false,
      refusal: "invalid",
      fields: [
        { field: "startDate", code: "start_past" },
        { field: "county", code: "unknown_county" },
        { field: "venue", code: "other" },
      ],
    });
    expect(eventRefusalOf(403, { detail: { code: "verification_required", message: "x" } }).refusal).toBe("verification");
    expect(eventRefusalOf(403, { detail: { code: "not_poster", message: "x" } }).refusal).toBe("notPoster");
    expect(eventRefusalOf(429, { detail: { code: "events_daily_limit", message: "x" } }).refusal).toBe("dailyLimit");
    expect(eventRefusalOf(409, { detail: { code: "changed_since_review", message: "x" } }).refusal).toBe("changedSinceReview");
    expect(eventRefusalOf(500, undefined).refusal).toBe("generic");
    expect(EVENT_CHIP).toEqual({ draft: "pending", published: "completed", rejected: "overdue", cancelled: "ended" });
    expect([cancellable("draft"), cancellable("published"), cancellable("rejected"), cancellable("cancelled")]).toEqual([true, true, false, false]);
  });
});

describe("the event form", () => {
  it("swaps the venue and county for the join address with the Online switch", () => {
    renderForm(calls());
    const online = screen.getByRole("switch", { name: "Online event" });
    expect(online.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByLabelText("Venue", { exact: false })).toBeTruthy();
    expect(screen.getByLabelText("County", { exact: false })).toBeTruthy();
    expect(screen.queryByLabelText("Join address", { exact: false })).toBeNull();
    fireEvent.click(online);
    expect(online.getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByLabelText("Venue", { exact: false })).toBeNull();
    expect(screen.queryByLabelText("County", { exact: false })).toBeNull();
    expect(screen.getByLabelText("Join address", { exact: false })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("marks the missing fields before sending and focuses the first", async () => {
    const api = calls();
    renderForm(api);
    await act(async () => fireEvent.submit(document.querySelector("form")!));
    expect(api.post).not.toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("event-title");
    expect(screen.getAllByText("Fill this in.").length).toBeGreaterThan(0);
    expect(screen.getByText("Add the venue of the event.")).toBeTruthy();
    expect(screen.getByText("Choose the county of the venue.")).toBeTruthy();
  });

  async function filledAndSent(api: EventCalls) {
    renderForm(api);
    fill("Title", "Meetup");
    fill("Description", "Talks and questions.");
    const dates = screen.getAllByLabelText("Date");
    const times = screen.getAllByLabelText("Time");
    fireEvent.change(dates[0], { target: { value: "2026-11-22" } });
    fireEvent.change(times[0], { target: { value: "18:00" } });
    fireEvent.change(dates[1], { target: { value: "2026-11-22" } });
    fireEvent.change(times[1], { target: { value: "20:30" } });
    fill("Venue", "Hub, Westlands");
    fireEvent.change(screen.getByLabelText("County", { exact: false, selector: "select" }), { target: { value: "KE-30" } });
    await act(async () => fireEvent.submit(document.querySelector("form")!));
  }

  it("posts for review and opens the new event's page", async () => {
    const api = calls();
    await filledAndSent(api);
    expect(api.post).toHaveBeenCalledWith(
      { kind: "org", orgId: "o1" },
      expect.objectContaining({ starts_at: "2026-11-22T18:00:00+03:00", county_code: "KE-30", online: false, join_url: null }),
    );
    expect(router.push).toHaveBeenCalledWith(`/org/events/${EVENT_ID}?org=o1`);
  });

  it("shows the API's 422 under each field and focuses the first", async () => {
    const api = calls({
      post: vi.fn(async () => ({
        ok: false as const,
        refusal: "invalid" as const,
        fields: [
          { field: "startDate" as const, code: "start_past" as const },
          { field: "venue" as const, code: "control_character" as const },
        ],
      })),
    });
    await filledAndSent(api);
    expect(screen.getByText("Choose a start time that has not passed.")).toBeTruthy();
    expect(screen.getByText("Remove the hidden or control characters from this text.")).toBeTruthy();
    expect(document.activeElement?.id).toBe("event-startDate");
    expect(document.querySelector("[data-refusal]")?.getAttribute("data-refusal")).toBe("invalid");
    expect(router.push).not.toHaveBeenCalled();
  });

  it("says why a post was refused, focused", async () => {
    const api = calls({ post: vi.fn(async () => ({ ok: false as const, refusal: "verification" as const, fields: [] })) });
    await filledAndSent(api);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("Telco A can post events once its legal verification is complete.");
    expect(document.activeElement).toBe(alert);
  });
});

describe("Cancel this event", () => {
  it("asks first, then cancels and reads the page again", async () => {
    const api = calls();
    renderWithIntl(<CancelEvent target={{ kind: "org", orgId: "o1" }} eventId={EVENT_ID} poster="Telco A" calls={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel this event" }));
    expect(screen.getByText("Developers no longer see it and no reminder of it is sent. This cannot be undone.")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancel the event" })));
    expect(api.cancel).toHaveBeenCalledWith({ kind: "org", orgId: "o1" }, EVENT_ID);
    expect(router.refresh).toHaveBeenCalled();
  });

  it("keeps a refusal in the dialog in words", async () => {
    const api = calls({ cancel: vi.fn(async () => ({ ok: false as const, refusal: "forbidden" as const, fields: [] })) });
    renderWithIntl(<CancelEvent target={{ kind: "staff" }} eventId={EVENT_ID} poster="Platform" calls={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel this event" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancel the event" })));
    expect(screen.getByText("Only an owner, admin, signatory or reviewer of Platform can post or cancel its events.")).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });
});
