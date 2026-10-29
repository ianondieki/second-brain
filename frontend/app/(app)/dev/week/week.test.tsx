import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import type { ReminderCalls } from "../events/calls";
import { RemindMe, type RemindMeLabels } from "../events/[id]/RemindMe";
import { reminderLine, reminderRefusal } from "../events/reminder";
import { byDay, calendarHref, eventDay, longDay, spansDays, type Week, type WeekEvent } from "./week";
import { WeekStrip } from "./WeekStrip";

// REQ-DEV-02 (P22-BF; D-60, D-61): This week on screen. Home's read stands whatever the API says (only a lost session
// leaves Home); the strip in its states; the week's grouping by Nairobi day; Remind me's states and lines.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirect(path),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@/lib/api/server", () => ({ forwardHeaders: async () => ({}), serverApi: () => ({ GET }) }));
vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

const { emailState, eventPage, weekStrip } = await import("./data");

const status = (code: number, errorCode = "x") => ({
  data: undefined,
  error: { detail: { code: errorCode, message: "x" } },
  response: new Response(null, { status: code }),
});

export function weekEvent(overrides: Partial<WeekEvent> = {}): WeekEvent {
  const id = overrides.id ?? "01a11043-1017-70dc-b565-dfbe1df95846";
  return {
    id,
    title: "Nairobi mobile money developers meetup",
    organiser: "Telco A",
    starts_at: "2026-11-22T18:00:00+03:00",
    ends_at: "2026-11-22T20:30:00+03:00",
    online: false,
    venue: "Innovation Hub, Westlands",
    county_code: "KE-30",
    county_name: "Nairobi City",
    join_url: null,
    link: "https://events.example/meetup",
    reminder: false,
    calendar_url: `/api/events/${id}/calendar.ics`,
    google_calendar_url: "https://calendar.google.com/calendar/render?action=TEMPLATE",
    ...overrides,
  };
}

const TREND: NonNullable<Week["trend"]> = {
  id: "01a11043-12b8-7ece-a327-a07f0b72f644",
  title: "Unvalidated npm trusted publishing configurations now expire",
  summary: "They expire 48 hours after creation.",
  topic_slug: "security",
  published_at: "2026-11-20T11:09:53+03:00",
  reviewed_on: "2026-11-20",
  seeded_example: true,
};

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});
afterEach(cleanup);

describe("Home's This week read", () => {
  it("gives the week", async () => {
    const week: Week = { events: [weekEvent()], trend: TREND, reminders_email: "on" };
    GET.mockResolvedValueOnce({ data: week, response: new Response(null, { status: 200 }) });
    await expect(weekStrip()).resolves.toEqual(week);
    expect(GET).toHaveBeenCalledWith("/api/me/week", expect.objectContaining({ cache: "no-store" }));
  });

  it("leaves the strip out on 404, 500, a timeout and offline, and never shows the error page", async () => {
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(weekStrip()).resolves.toBeNull();
    GET.mockResolvedValueOnce(status(500));
    await expect(weekStrip()).resolves.toBeNull();
    GET.mockRejectedValueOnce(Object.assign(new Error("timed out"), { name: "TimeoutError" }));
    await expect(weekStrip()).resolves.toBeNull();
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(weekStrip()).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(weekStrip()).rejects.toThrow("NEXT_REDIRECT /login");
  });

  it("reads the email gate from the same answer, or none", async () => {
    GET.mockResolvedValueOnce({ data: { events: [], trend: null, reminders_email: "no_consent" }, response: new Response(null, { status: 200 }) });
    await expect(emailState()).resolves.toBe("no_consent");
    GET.mockResolvedValueOnce(status(500));
    await expect(emailState()).resolves.toBeNull();
  });

  it("answers an unknown, unpublished or malformed event with the not-found page", async () => {
    await expect(eventPage("not-a-uuid")).rejects.toThrow("NEXT_NOT_FOUND");
    expect(GET).not.toHaveBeenCalled();
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(eventPage(weekEvent().id)).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("Home's This week strip", () => {
  it("is left out when the read failed", async () => {
    expect(await WeekStrip({ week: null })).toBeNull();
  });

  it("says one sentence with its link when nothing is near and there is no trend", async () => {
    render(await resolveServerTree(await WeekStrip({ week: { events: [], trend: null, reminders_email: "on" } })));
    const section = screen.getByRole("region", { name: "This week" });
    expect(within(section).getByText("Nothing near you this week. Online events count too.")).toBeTruthy();
    expect(within(section).getByRole("link", { name: "See the week" }).getAttribute("href")).toBe("/dev/week");
    expect(section.querySelector("[data-primary]")).toBeNull();
  });

  it("lists the events with when, where and who, then the trend of the day", async () => {
    const online = weekEvent({
      id: "01a11043-1197-70c6-9644-6e0fc2dc9fc1",
      title: "Secure publishing clinic",
      organiser: "Platform",
      online: true,
      venue: null,
      county_code: null,
      county_name: null,
      starts_at: "2026-11-24T10:00:00+03:00",
      ends_at: "2026-11-24T11:30:00+03:00",
      reminder: true,
    });
    render(await resolveServerTree(await WeekStrip({ week: { events: [weekEvent(), online], trend: TREND, reminders_email: "on" } })));
    const rows = document.querySelectorAll("[data-week-event]");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Sun 22 Nov · 18:00");
    expect(rows[0].textContent).toContain("Nairobi City");
    expect(rows[0].textContent).toContain("By Telco A");
    expect(within(rows[0] as HTMLElement).getByRole("link", { name: "Nairobi mobile money developers meetup" }).getAttribute("href")).toBe(
      "/dev/events/01a11043-1017-70dc-b565-dfbe1df95846",
    );
    expect(rows[1].textContent).toContain("Tue 24 Nov · 10:00");
    expect(rows[1].textContent).toContain("Online");
    expect(rows[1].querySelector("[data-reminder-set]")?.textContent).toBe("Reminder set");
    const trend = document.querySelector("[data-week-trend]") as HTMLElement;
    expect(trend.textContent).toContain("Trend");
    expect(within(trend).getByRole("link", { name: TREND.title }).getAttribute("href")).toBe(`/dev/trends/${TREND.id}`);
    expect(trend.querySelector(".line-clamp-1")?.textContent).toBe(TREND.summary);
    expect(document.querySelector("[data-week-empty]")).toBeNull();
  });
});

describe("the week's rules", () => {
  it("writes days and groups by the Nairobi day, soonest first", () => {
    expect(eventDay("en", "2026-11-22T18:00:00+03:00")).toBe("Sun 22 Nov");
    // 22:30 UTC on the 21st is already Sunday the 22nd in Nairobi.
    expect(eventDay("en", "2026-11-21T22:30:00Z")).toBe("Sun 22 Nov");
    expect(longDay("en", "2026-11-22T18:00:00+03:00")).toBe("Sunday, 22 November");
    const a = weekEvent({ id: "a", starts_at: "2026-11-22T09:00:00+03:00" });
    const b = weekEvent({ id: "b", starts_at: "2026-11-21T22:30:00Z" });
    const c = weekEvent({ id: "c", starts_at: "2026-11-24T10:00:00+03:00" });
    expect(byDay([a, b, c]).map((g) => [g.day, g.events.map((e) => e.id)])).toEqual([
      ["2026-11-22", ["a", "b"]],
      ["2026-11-24", ["c"]],
    ]);
    expect(spansDays(weekEvent({ starts_at: "2026-11-21T18:00:00+03:00", ends_at: "2026-11-22T12:00:00+03:00" }))).toBe(true);
    expect(spansDays(weekEvent())).toBe(false);
  });

  it("links the API's own .ics path only", () => {
    expect(calendarHref("/api/events/01a11043-1017-70dc-b565-dfbe1df95846/calendar.ics")).toBe(
      "/api/events/01a11043-1017-70dc-b565-dfbe1df95846/calendar.ics",
    );
    expect(calendarHref("https://evil.example/x.ics")).toBeNull();
  });

  it("words the email gate and the refusals", () => {
    expect(reminderLine("on")).toBe("both");
    expect(reminderLine("no_consent")).toBe("noConsent");
    expect(reminderLine("unverified")).toBe("unverified");
    expect(reminderRefusal(404, { detail: { code: "not_found", message: "x" } })).toBe("gone");
    expect(reminderRefusal(401, undefined)).toBe("signedOut");
    expect(reminderRefusal(500, undefined)).toBe("generic");
  });
});

describe("Remind me", () => {
  const labels: RemindMeLabels = {
    remind: "Remind me",
    reminding: "Setting the reminder…",
    decline: "Don't remind me",
    declining: "Removing the reminder…",
    set: "Reminder set.",
    removed: "Reminder removed. Nothing will be sent.",
    refusal: { gone: "Gone.", signedOut: "Signed out.", generic: "Try again." },
  };
  const lines = {
    both: "An email the day before and a notice here on the morning.",
    noConsent: (
      <>
        A notice here on the morning. Email reminders are off in <a href="/settings/notifications">Settings</a>.
      </>
    ),
    unverified: "A notice here on the morning. Verify your email for the email reminder.",
  };
  function calls(overrides: Partial<ReminderCalls> = {}): ReminderCalls {
    return {
      remind: vi.fn(async () => ({ ok: true as const, value: { email: "on" as const } })),
      decline: vi.fn(async () => ({ ok: true as const, value: null })),
      ...overrides,
    };
  }

  it("is the one primary action with what would come, then the secondary decline with what will, focused", async () => {
    const api = calls();
    render(<RemindMe eventId="e1" initial={false} email="on" labels={labels} lines={lines} calls={api} />);
    const button = screen.getByRole("button", { name: "Remind me" });
    expect(button.hasAttribute("data-primary")).toBe(true);
    expect(screen.getByRole("status").textContent).toBe(lines.both);
    await act(async () => fireEvent.click(button));
    expect(api.remind).toHaveBeenCalledWith("e1");
    const decline = screen.getByRole("button", { name: "Don't remind me" });
    expect(decline.hasAttribute("data-primary")).toBe(false);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe(`Reminder set.${lines.both}`);
    expect(document.activeElement).toBe(status);

    await act(async () => fireEvent.click(decline));
    expect(api.decline).toHaveBeenCalledWith("e1");
    expect(screen.getByRole("button", { name: "Remind me" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(labels.removed);
  });

  it("says the email is off with the way to Settings, from the API's answer", async () => {
    const api = calls({ remind: vi.fn(async () => ({ ok: true as const, value: { email: "no_consent" as const } })) });
    render(<RemindMe eventId="e1" initial={false} email={null} labels={labels} lines={lines} calls={api} />);
    expect(screen.getByRole("status").textContent).toBe("");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remind me" })));
    expect(screen.getByRole("status").textContent).toContain("Email reminders are off in Settings.");
    expect(within(screen.getByRole("status")).getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings/notifications");
  });

  it("says when the address needs verifying", () => {
    render(<RemindMe eventId="e1" initial email="unverified" labels={labels} lines={lines} calls={calls()} />);
    expect(screen.getByRole("button", { name: "Don't remind me" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(`Reminder set.${lines.unverified}`);
  });

  it("keeps the state and says why when the call is refused", async () => {
    const api = calls({ remind: vi.fn(async () => ({ ok: false as const, refusal: "gone" as const })) });
    render(<RemindMe eventId="e1" initial={false} email="on" labels={labels} lines={lines} calls={api} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remind me" })));
    expect(screen.getByRole("button", { name: "Remind me" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Gone.");
    expect(document.activeElement).toBe(screen.getByRole("status"));
  });
});
