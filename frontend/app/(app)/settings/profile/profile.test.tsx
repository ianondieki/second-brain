import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Profile } from "@/app/(app)/dev/teams/teams";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { BlockedList } from "./BlockedList";
import { profileChange, type ProfileCalls } from "./calls";
import { ProfileForm } from "./ProfileForm";

// REQ-DEV-03 (P22-CF; D-58): Settings › Profile. The headline, the county and "Visible to peers" with its one sentence
// are kept with Save (the one primary action; only what changed is sent); a status line takes focus; the blocked
// developers each have Unblock.

afterEach(cleanup);

const PROFILE: Profile = {
  handle: "dev-9edxrg2a",
  verification_level: "d1",
  headline: null,
  bio: null,
  county_code: "KE-30",
  county_name: "Nairobi City",
  peers_visible: false,
};
const COUNTIES = [
  { code: "KE-01", name: "Mombasa" },
  { code: "KE-30", name: "Nairobi City" },
];

describe("what Save sends", () => {
  it("only the fields that changed; an empty headline clears it", () => {
    expect(profileChange(PROFILE, { headline: "", county: "KE-30", visible: false })).toEqual({});
    expect(profileChange(PROFILE, { headline: "  USSD  ", county: "KE-01", visible: true })).toEqual({
      headline: "USSD",
      county_code: "KE-01",
      peers_visible: true,
    });
    expect(profileChange({ ...PROFILE, headline: "Old" }, { headline: " ", county: "", visible: false })).toEqual({ headline: null, county_code: null });
  });
});

describe("the profile form", () => {
  function open(save: ProfileCalls["save"]) {
    renderWithIntl(<ProfileForm initial={PROFILE} counties={COUNTIES} calls={{ save }} />);
  }

  it("shows the handle, the fields, the switch with its one sentence, and Save as the one primary action", () => {
    open(vi.fn());
    expect(screen.getByText("Your handle: dev-9edxrg2a")).toBeTruthy();
    expect((screen.getByLabelText("Headline") as HTMLInputElement).maxLength).toBe(160);
    expect((screen.getByLabelText("County") as HTMLSelectElement).value).toBe("KE-30");
    const toggle = screen.getByRole("switch", { name: "Visible to peers" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    const explain = document.getElementById(toggle.getAttribute("aria-describedby")!)!;
    expect(explain.textContent).toBe(
      "Developers in your county or niches can see your handle, headline and shared niches. Never organisations.",
    );
    const primary = document.querySelectorAll("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Save");
  });

  it("keeps nothing until Save; then says it is saved and the line takes focus", async () => {
    const save = vi.fn(async () => ({ ok: true as const, profile: { ...PROFILE, peers_visible: true, headline: "USSD" } }));
    open(save);
    fireEvent.click(screen.getByRole("switch", { name: "Visible to peers" }));
    fireEvent.change(screen.getByLabelText("Headline"), { target: { value: "USSD" } });
    expect(save).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    expect(save).toHaveBeenCalledWith({ headline: "USSD", peers_visible: true });
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Profile saved.");
    await waitFor(() => expect(document.activeElement).toBe(status));
    // Saved: a second Save sends nothing.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("says the county limit and other refusals in one sentence", async () => {
    const save = vi.fn(async () => ({ ok: false as const, refusal: "tooMany" as const }));
    open(save);
    fireEvent.change(screen.getByLabelText("County"), { target: { value: "KE-01" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    expect(screen.getByRole("alert").textContent).toBe(en.profileSettings.tooMany);
  });
});

describe("the blocked developers", () => {
  it("Unblock lifts a block, says so and takes focus", async () => {
    const unblock = vi.fn(async () => true);
    renderWithIntl(
      <BlockedList
        initial={[
          { user_id: "a", handle: "dev-a", blocked_at: "2026-10-06T10:00:00+03:00" },
          { user_id: "b", handle: "dev-b", blocked_at: "2026-10-06T11:00:00+03:00" },
        ]}
        calls={{ unblock }}
      />,
    );
    const row = document.querySelector('[data-blocked="dev-a"]') as HTMLElement;
    await act(async () => fireEvent.click(within(row).getByRole("button", { name: "Unblock" })));
    expect(unblock).toHaveBeenCalledWith("a");
    expect(document.querySelector('[data-blocked="dev-a"]')).toBeNull();
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("dev-a is unblocked. Threads that closed stay closed.");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(document.querySelector("[data-primary]")).toBeNull();
  });
});
