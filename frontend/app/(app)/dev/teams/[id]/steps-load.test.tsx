import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { toThreadPage, type TeamThread as TeamThreadRead } from "../teams";
import { STEP_STATUS_ID, STEPS_ID } from "./ids";
import { StepButtons } from "./StepButtons";
import { TeamThread } from "./TeamThread";

// REQ-DEV-03 (P22-CF review): when the steps' module cannot be loaded (offline, a new deploy), a press says so in one
// sentence where the step's dialog would open; the page stays.

vi.mock("./later", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
afterEach(cleanup);

const READ: TeamThreadRead = {
  thread: {
    id: "01a11223-32cd-732d-9755-f7206d3c33e4",
    counterpart: { user_id: "u2", handle: "dev-kb3dysnk", headline: null },
    problem: { id: "p1", title: "Tower sites go down" },
    created_at: "2026-10-06T10:00:00+03:00",
    last_message_at: null,
    unread: 0,
    open: true,
    closed_at: null,
    closed_reason: null,
  },
  can_post: true,
  max_chars: 4000,
  last_read_at: null,
  items: [],
  next_cursor: null,
};

describe("a step whose module cannot load", () => {
  it("says so in one sentence and keeps the page", async () => {
    renderWithIntl(
      <>
        <div id={STEP_STATUS_ID} />
        <div id={STEPS_ID} inert>
          <StepButtons credit={null} more="More options" leave="Leave thread" block="Block dev-kb3dysnk" />
        </div>
        <TeamThread
          threadId={READ.thread.id}
          initial={toThreadPage(READ, "dev-kb3dysnk")}
          counterpart="dev-kb3dysnk"
          today="2026-10-06"
          locale="en"
          empty={null}
          person={{ user_id: "u2", handle: "dev-kb3dysnk" }}
          ideas={[]}
        />
      </>,
    );
    // Hydrated: the steps answer.
    expect(document.getElementById(STEPS_ID)?.hasAttribute("inert")).toBe(false);
    await act(async () => fireEvent.click(document.querySelector("[data-block]") as HTMLElement));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(en.teamUp.thread.loadFailed);
    expect(document.getElementById(STEP_STATUS_ID)?.contains(alert)).toBe(true);
    expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
  });
});
