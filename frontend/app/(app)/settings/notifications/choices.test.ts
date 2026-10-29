import { describe, expect, it } from "vitest";

import {
  CHANNELS,
  changedDecisions,
  isOffered,
  notificationChoices,
  saveRefusal,
  type ConsentItem,
} from "./choices";

// REQ-CON-01, REQ-NOT-03: which consents the notification settings offer, what a save sends, and the fixed sentence
// each refusal gets.

const item = (purpose: ConsentItem["purpose"], granted = false, version = "2026-09-29.2"): ConsentItem => ({
  purpose,
  granted,
  text: `Wording of ${purpose}.`,
  version,
});

const ALL: ConsentItem[] = [
  item("marketing"),
  item("reminders", true),
  item("whatsapp"),
  item("profiling", true),
  item("github_import"),
  item("tier2_llm_moderation"),
];

describe("the choices on the page", () => {
  it("offers the messages we send (reminders, news, WhatsApp) grouped by channel, in that order", () => {
    const choices = notificationChoices(ALL);
    expect(choices.map((c) => c.purpose)).toEqual(["reminders", "marketing", "whatsapp"]);
    expect(CHANNELS.email).toEqual(["reminders", "marketing"]);
    expect(CHANNELS.whatsapp).toEqual(["whatsapp"]);
  });

  it("leaves out consents that are not about notifications (asked for where they apply)", () => {
    const purposes = notificationChoices(ALL).map((c) => c.purpose);
    for (const other of ["profiling", "github_import", "tier2_llm_moderation", "tier2_llm_assistant"]) {
      expect(purposes).not.toContain(other);
    }
  });

  it("keeps the API's wording, decision and version verbatim", () => {
    const [reminders] = notificationChoices(ALL);
    expect(reminders).toEqual({ purpose: "reminders", granted: true, text: "Wording of reminders.", version: "2026-09-29.2" });
  });

  it("skips a purpose the API does not list", () => {
    expect(notificationChoices([item("marketing")]).map((c) => c.purpose)).toEqual(["marketing"]);
    expect(notificationChoices([])).toEqual([]);
  });

  it("offers WhatsApp only to turn it off: it is not available yet", () => {
    expect(isOffered(item("whatsapp", false))).toBe(false);
    expect(isOffered(item("whatsapp", true))).toBe(true);
    expect(isOffered(item("reminders", false))).toBe(true);
    expect(isOffered(item("marketing", true))).toBe(true);
  });
});

describe("what a save sends", () => {
  const shown = notificationChoices(ALL);

  it("sends only the changed decisions, each with the version whose wording was shown", () => {
    expect(changedDecisions(shown, { reminders: false, marketing: true, whatsapp: false })).toEqual({
      reminders: { granted: false, version: "2026-09-29.2" },
      marketing: { granted: true, version: "2026-09-29.2" },
    });
  });

  it("sends nothing when nothing changed", () => {
    expect(changedDecisions(shown, { reminders: true, marketing: false, whatsapp: false })).toEqual({});
    expect(changedDecisions(shown, {})).toEqual({});
  });

  it("never turns on a choice that is not offered", () => {
    expect(changedDecisions(shown, { whatsapp: true })).toEqual({});
  });

  it("sends a purpose's own version when versions differ", () => {
    const mixed = notificationChoices([item("reminders", false, "v1"), item("marketing", false, "v2")]);
    expect(changedDecisions(mixed, { reminders: true, marketing: true })).toEqual({
      reminders: { granted: true, version: "v1" },
      marketing: { granted: true, version: "v2" },
    });
  });
});

describe("refusals", () => {
  it("names a change of wording (409 consent_text_changed)", () => {
    expect(saveRefusal(409, { detail: { code: "consent_text_changed", message: "anything" } })).toBe("changed");
  });

  it("maps every other answer to a fixed refusal, never the API's message", () => {
    expect(saveRefusal(0, undefined)).toBe("network");
    expect(saveRefusal(401, { detail: { code: "not_authenticated" } })).toBe("signedOut");
    expect(saveRefusal(429, { detail: { code: "rate_limited" } })).toBe("rateLimited");
    expect(saveRefusal(409, { detail: { code: "something_else" } })).toBe("failed");
    expect(saveRefusal(422, { detail: { code: "consent_session_only" } })).toBe("failed");
    expect(saveRefusal(403, { detail: { code: "csrf_failed" } })).toBe("failed");
    expect(saveRefusal(500, "Internal Server Error")).toBe("failed");
  });
});
