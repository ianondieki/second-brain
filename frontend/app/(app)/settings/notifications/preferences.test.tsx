import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { savePreference, type PreferenceOutcome, type SaveOutcome } from "./calls";
import { notificationChoices, preferenceChoices, type ConsentItem, type PreferenceItem } from "./choices";
import { NotificationChoices } from "./NotificationChoices";

// REQ-PERS-03, REQ-NOT-06 (P21 track C6): the saved-search digest by email, a notification preference (its own store,
// GET/PUT /api/me/notification-preferences) beside the consents, off by default, saved with "Save choices".

afterEach(cleanup);

const VERSION = "2026-09-29.2";
const REMINDERS = "Send me reminders about my proposals and engagements by email.";
const DIGEST = en.notificationSettings.preference.saved_search_digest;

const consents: ConsentItem[] = [{ purpose: "reminders", granted: true, text: REMINDERS, version: VERSION }];
const digest = (enabled: boolean): PreferenceItem => ({
  kind: "saved_search_digest",
  channel: "email",
  label: "A daily email with how many new problems or Briefs match your saved searches",
  default: false,
  enabled,
});

describe("the notification preferences", () => {
  it("keeps the email and WhatsApp ones and words each in the page's language when it can", () => {
    const items = [digest(false), { ...digest(true), kind: "other_kind", label: "API words" }, { ...digest(true), channel: "in_app" as const }];
    const choices = preferenceChoices(items, (item) => (item.kind === "saved_search_digest" ? DIGEST : item.label));
    expect(choices).toEqual([
      { kind: "saved_search_digest", channel: "email", enabled: false, label: DIGEST },
      { kind: "other_kind", channel: "email", enabled: true, label: "API words" },
    ]);
  });

  it("shows the digest in the Email group, off, and saves a change with Save choices", async () => {
    const saveImpl = vi.fn<(body: unknown) => Promise<SaveOutcome>>();
    const savePreferenceImpl = vi.fn(async (): Promise<PreferenceOutcome> => ({ ok: true, items: [digest(true)] }));
    renderWithIntl(
      <NotificationChoices
        initial={notificationChoices(consents)}
        preferences={preferenceChoices([digest(false)], () => DIGEST)}
        saveImpl={saveImpl}
        savePreferenceImpl={savePreferenceImpl}
      />,
    );
    const email = screen.getByRole("group", { name: "Email" });
    const box = within(email).getByRole("checkbox", { name: DIGEST });
    expect(box).toHaveProperty("checked", false);
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Save choices" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(en.notificationSettings.saved));
    expect(savePreferenceImpl).toHaveBeenCalledWith({ kind: "saved_search_digest", channel: "email", enabled: true });
    expect(saveImpl).not.toHaveBeenCalled(); // no consent changed
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("says why when the preference is refused", async () => {
    const savePreferenceImpl = vi.fn(async (): Promise<PreferenceOutcome> => ({ ok: false, refusal: "network" }));
    renderWithIntl(
      <NotificationChoices
        initial={notificationChoices(consents)}
        preferences={preferenceChoices([digest(false)], () => DIGEST)}
        savePreferenceImpl={savePreferenceImpl}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: DIGEST }));
    fireEvent.click(screen.getByRole("button", { name: "Save choices" }));
    expect((await screen.findByRole("alert")).textContent).toContain(en.notificationSettings.refused.network);
  });

  it("PUTs one preference to /api/me/notification-preferences", async () => {
    const PUT = vi.fn(async () => ({ data: { items: [digest(true)] }, response: new Response(null, { status: 200 }) }));
    const body = { kind: "saved_search_digest", channel: "email" as const, enabled: true };
    expect(await savePreference(body, { PUT } as unknown as ApiClient)).toEqual({ ok: true, items: [digest(true)] });
    expect(PUT).toHaveBeenCalledWith("/api/me/notification-preferences", { body });
  });
});
