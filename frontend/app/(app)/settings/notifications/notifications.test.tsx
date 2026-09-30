import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { SaveOutcome } from "./calls";
import { notificationChoices, type ConsentItem } from "./choices";
import { NotificationChoices } from "./NotificationChoices";

// REQ-CON-01, REQ-NOT-03 (docs/spec/07 item 1 "Notification settings"): the consents' wording verbatim, one primary
// action, a save on the version shown, and a fixed sentence for every refusal.

afterEach(cleanup);

const VERSION = "2026-09-29.2";
const REMINDERS = "Send me reminders about my proposals and engagements by email.";
const MARKETING = "Send me occasional product news by email. You can stop at any time.";
const WHATSAPP = "Send me reminders on WhatsApp (available later).";

function consents({ reminders = true, marketing = false, whatsapp = false } = {}): ConsentItem[] {
  return [
    { purpose: "marketing", granted: marketing, text: MARKETING, version: VERSION },
    { purpose: "reminders", granted: reminders, text: REMINDERS, version: VERSION },
    { purpose: "whatsapp", granted: whatsapp, text: WHATSAPP, version: VERSION },
    { purpose: "profiling", granted: true, text: "Use my niches and activity.", version: VERSION },
  ];
}

function renderChoices(items: ConsentItem[], saveImpl = vi.fn<(body: unknown) => Promise<SaveOutcome>>()) {
  renderWithIntl(<NotificationChoices initial={notificationChoices(items)} saveImpl={saveImpl} />);
  return saveImpl;
}

const save = () => fireEvent.click(screen.getByRole("button", { name: "Save choices" }));

describe("the notification settings", () => {
  it("labels each choice with the API's wording, grouped by channel, with one primary action", () => {
    renderChoices(consents());
    const email = screen.getByRole("group", { name: "Email" });
    expect(within(email).getAllByRole("checkbox").map((box) => box.getAttribute("name"))).toEqual(["reminders", "marketing"]);
    expect(within(email).getByRole("checkbox", { name: REMINDERS })).toHaveProperty("checked", true);
    expect(within(email).getByRole("checkbox", { name: MARKETING })).toHaveProperty("checked", false);
    const whatsapp = screen.getByRole("group", { name: "WhatsApp" });
    expect(within(whatsapp).getByRole("checkbox", { name: WHATSAPP })).toBeTruthy();
    expect(screen.queryByText("Use my niches and activity.")).toBeNull();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(document.querySelector("[data-primary]")?.textContent).toBe("Save choices");
  });

  it("shows WhatsApp as not available: it cannot be turned on", () => {
    renderChoices(consents());
    const box = screen.getByRole("checkbox", { name: WHATSAPP });
    expect(box).toHaveProperty("disabled", true);
    const hint = document.getElementById(box.getAttribute("aria-describedby")!);
    expect(hint?.textContent).toBe("WhatsApp messages are not available yet, so this cannot be turned on.");
  });

  it("lets a person who opted in to WhatsApp turn it off", async () => {
    const saveImpl = renderChoices(consents({ whatsapp: true }));
    saveImpl.mockResolvedValue({ ok: true, items: consents({ whatsapp: false }) });
    const box = screen.getByRole("checkbox", { name: WHATSAPP });
    expect(box).toHaveProperty("disabled", false);
    fireEvent.click(box);
    save();
    await screen.findByText("Your choices are saved.");
    expect(saveImpl).toHaveBeenCalledWith({ whatsapp: { granted: false, version: VERSION } });
    expect(screen.getByRole("checkbox", { name: WHATSAPP })).toHaveProperty("disabled", true);
  });

  it("saves the changed choices on the version shown and confirms", async () => {
    const saveImpl = renderChoices(consents());
    saveImpl.mockResolvedValue({ ok: true, items: consents({ reminders: false, marketing: true }) });
    fireEvent.click(screen.getByRole("checkbox", { name: REMINDERS }));
    fireEvent.click(screen.getByRole("checkbox", { name: MARKETING }));
    save();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Your choices are saved."));
    expect(saveImpl).toHaveBeenCalledTimes(1);
    expect(saveImpl).toHaveBeenCalledWith({
      reminders: { granted: false, version: VERSION },
      marketing: { granted: true, version: VERSION },
    });
    expect(screen.getByRole("checkbox", { name: REMINDERS })).toHaveProperty("checked", false);
    expect(screen.getByRole("checkbox", { name: MARKETING })).toHaveProperty("checked", true);
    // A new change clears the confirmation until it is saved.
    fireEvent.click(screen.getByRole("checkbox", { name: MARKETING }));
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("sends nothing when nothing changed", async () => {
    const saveImpl = renderChoices(consents());
    save();
    await screen.findByText("Your choices are saved.");
    expect(saveImpl).not.toHaveBeenCalled();
  });

  it("refuses with a fixed sentence when the wording changed (409), with Reload as its one action", async () => {
    const saveImpl = renderChoices(consents());
    saveImpl.mockResolvedValue({ ok: false, refusal: "changed" });
    fireEvent.click(screen.getByRole("checkbox", { name: MARKETING }));
    save();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/^The wording/).textContent).toBe(
      "The wording of these choices changed after you opened this page, so nothing was saved.",
    );
    expect(within(alert).getAllByRole("link")).toHaveLength(1);
    expect(within(alert).getByRole("link", { name: "Reload the page" }).getAttribute("href")).toBe(
      "/settings/notifications",
    );
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it.each([
    ["signedOut", "You are signed out, so nothing was saved.", "Log in"],
    ["rateLimited", "Nothing was saved because of too many saves in a short time; wait a minute and save again.", null],
    ["network", "Nothing was saved because the connection failed; check it and save again.", null],
    ["failed", "Nothing was saved; try again in a moment.", null],
  ] as const)("words a %s refusal as one fixed sentence", async (refusal, sentence, action) => {
    const saveImpl = renderChoices(consents());
    saveImpl.mockResolvedValue({ ok: false, refusal });
    fireEvent.click(screen.getByRole("checkbox", { name: REMINDERS }));
    save();
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("[data-refusal]")?.textContent).toBe(sentence);
    expect(within(alert).queryAllByRole("link").map((link) => link.textContent)).toEqual(action ? [action] : []);
    // The choice stays as the person left it, so they can save again.
    expect(screen.getByRole("checkbox", { name: REMINDERS })).toHaveProperty("checked", false);
  });
});
