import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventOut } from "@/components/events/event-draft";
import { renderWithIntl } from "@/test/intl";

import type { AdminEventCalls, DecisionOutcome } from "./calls";
import { EventDecision } from "./EventDecision";
import { decisionNext, decisionRefusalOf, eventsView, eventsViewHref, queueOrder } from "./events";

// REQ-DEV-02 (P22-BF; D-60): the staff events queue. Its views and order, the decision's refusals in words, the
// decision behind a confirmation and the step-up, sending the version the page read.

const router = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const confirmStepUp = vi.hoisted(() => vi.fn(async () => ({ ok: true as const })));
vi.mock("../research/calls", () => ({ confirmStepUp }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => router.refresh.mockReset());
afterEach(cleanup);

const SEEN = "2026-11-20T10:00:00.123456+03:00";
const err = (code: string) => ({ detail: { code, message: "x" } });

function event(id: string, status: EventOut["status"], starts_at: string): EventOut {
  return {
    id,
    org_id: null,
    organiser: "Platform",
    title: id,
    description: "d",
    starts_at,
    ends_at: starts_at,
    online: true,
    venue: null,
    county_code: null,
    county_name: null,
    join_url: "https://meet.example/x",
    link: null,
    status,
    decided_at: null,
    cancelled_at: null,
    created_at: "2026-11-20T10:00:00+03:00",
    updated_at: SEEN,
  };
}

function calls(...outcomes: DecisionOutcome[]): AdminEventCalls {
  const decide = vi.fn();
  for (const outcome of outcomes) decide.mockResolvedValueOnce(outcome);
  decide.mockResolvedValue({ ok: true, value: event("e1", "published", "2026-11-24T10:00:00+03:00") });
  return { decide };
}

async function decide(name: "Publish" | "Reject") {
  fireEvent.click(screen.getByRole("button", { name }));
  const dialog = document.querySelector("dialog[open]") as HTMLDialogElement;
  const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === name)!;
  await act(async () => fireEvent.click(confirm));
}

describe("the events queue's rules", () => {
  it("opens on the events in review, soonest first; then published, then closed (rejected or cancelled)", () => {
    expect(eventsView(undefined)).toBe("draft");
    expect(eventsView("published")).toBe("published");
    expect(eventsView("nonsense")).toBe("draft");
    expect(eventsViewHref("draft")).toBe("/admin/events");
    expect(eventsView("cancelled")).toBe("draft");
    expect(eventsViewHref("closed")).toBe("/admin/events?view=closed");
    const items = [event("late", "draft", "2026-11-28T10:00:00+03:00"), event("soon", "draft", "2026-11-22T10:00:00+03:00")];
    expect(queueOrder("draft", items).map((e) => e.id)).toEqual(["soon", "late"]);
    expect(queueOrder("published", items)).toEqual([]);
    // Closed: rejected and cancelled together, the last changed first.
    const rejected = { ...event("rejected", "rejected", "2026-11-22T10:00:00+03:00"), updated_at: "2026-11-21T10:00:00+03:00" };
    const cancelled = { ...event("cancelled", "cancelled", "2026-11-22T10:00:00+03:00"), updated_at: "2026-11-21T12:00:00+03:00" };
    expect(queueOrder("closed", [rejected, ...items, cancelled]).map((e) => e.id)).toEqual(["cancelled", "rejected"]);
  });

  it("words each refusal and says what it leaves", () => {
    expect(decisionRefusalOf(403, err("step_up_required"))).toEqual({ kind: "stepUp" });
    expect(decisionRefusalOf(409, err("changed_since_review"))).toEqual({ kind: "refusal", code: "changedSinceReview" });
    expect(decisionRefusalOf(409, err("event_over"))).toEqual({ kind: "refusal", code: "eventOver" });
    expect(decisionRefusalOf(409, err("organisation_unavailable"))).toEqual({ kind: "refusal", code: "organisationUnavailable" });
    expect(decisionRefusalOf(409, err("already_decided"))).toEqual({ kind: "refusal", code: "alreadyDecided" });
    expect(decisionRefusalOf(404, err("not_found"))).toEqual({ kind: "refusal", code: "notFound" });
    expect(decisionRefusalOf(500, undefined)).toEqual({ kind: "refusal", code: "generic" });
    expect(decisionNext("changedSinceReview")).toBe("reload");
    expect(decisionNext("alreadyDecided")).toBe("reload");
    expect(decisionNext("eventOver")).toBe("reject");
    expect(decisionNext("organisationUnavailable")).toBe("reject");
    expect(decisionNext("generic")).toBe("retry");
  });
});

describe("the staff decision on an event", () => {
  it("publishes after the confirmation, sending the version the page read", async () => {
    const api = calls();
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("data-primary")).toBe(true);
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(false);
    await decide("Publish");
    expect(api.decide).toHaveBeenCalledWith("e1", "publish", SEEN);
    expect(screen.getByRole("status").textContent).toBe("Published. Developers see it now.");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("rejects after the confirmation", async () => {
    const api = calls();
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    await decide("Reject");
    expect(api.decide).toHaveBeenCalledWith("e1", "reject", SEEN);
    expect(screen.getByRole("status").textContent).toBe("Rejected. Developers do not see it.");
  });

  it("asks for a fresh code, then repeats the decision", async () => {
    const api = calls({ ok: false, refusal: { kind: "stepUp" } });
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    await decide("Publish");
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(confirmStepUp).toHaveBeenCalledWith("123456");
    expect(api.decide).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status").textContent).toBe("Published. Developers see it now.");
  });

  it("says the event changed since it was opened and reads the page again", async () => {
    const api = calls({ ok: false, refusal: { kind: "refusal", code: "changedSinceReview" } });
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    await decide("Publish");
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("This event changed since you opened it.");
    expect(document.activeElement).toBe(alert);
    expect(router.refresh).toHaveBeenCalled();
  });

  it("leaves only Reject, as the primary action, for an event that has ended", async () => {
    const api = calls({ ok: false, refusal: { kind: "refusal", code: "eventOver" } });
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    await decide("Publish");
    expect(screen.getByRole("alert").textContent).toBe("This event has ended, so it can be rejected but not published.");
    const publish = screen.getByRole("button", { name: "Publish" });
    expect(publish.getAttribute("aria-disabled")).toBe("true");
    expect(publish.hasAttribute("data-primary")).toBe(false);
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("says one sentence when the organisation can no longer publish", async () => {
    const api = calls({ ok: false, refusal: { kind: "refusal", code: "organisationUnavailable" } });
    renderWithIntl(<EventDecision eventId="e1" seen={SEEN} calls={api} />);
    await decide("Publish");
    expect(screen.getByRole("alert").textContent).toBe(
      "The organisation is no longer verified, or it is suspended or delisted. Reject the event.",
    );
  });
});
