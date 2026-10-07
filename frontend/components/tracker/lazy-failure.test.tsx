import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { Actions } from "./Actions";
import type { CommandOutcome } from "./calls";
import { LazyContactReveal, LazyShareTier2 } from "./lazy";
import { actionItems, type CommandRequest } from "./model";

// P23-3 review (PROGRESS.md: no code split may fail into a route's error boundary): when the chunk of one of the
// tracker's rarely shown parts cannot load (offline, a new deploy), that part says so in one sentence with a reload;
// the rest of the tracker, its primary action included, stays.

vi.mock("./ShareTier2", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
vi.mock("./ContactReveal", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
vi.mock("./StepUp", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
afterEach(cleanup);

const PRIMARY = <button data-primary="">Sign the mutual NDA</button>;

describe("a tracker part whose chunk cannot load", () => {
  it("the Tier-2 share says so in one sentence; the primary action stays", async () => {
    renderWithIntl(
      <>
        {PRIMARY}
        <LazyShareTier2 engagementId="e1" orgName="Telco A (fixture)" enrolled />
      </>,
    );
    expect((await screen.findByRole("alert")).textContent).toBe(`${en.trackerActions.partFailed}${en.trackerActions.partReload}`);
    expect(screen.getByRole("button", { name: en.trackerActions.partReload })).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("the contact reveal says so in one sentence; the primary action stays", async () => {
    renderWithIntl(
      <>
        {PRIMARY}
        <LazyContactReveal engagementId="e1" />
      </>,
    );
    expect((await screen.findByRole("alert")).textContent).toContain(en.trackerActions.partFailed);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("the fresh-code form says so where it would open, with a reload; the refused step did not run again", async () => {
    const run = vi.fn(async (): Promise<CommandOutcome> => ({ ok: false, refusal: "stepUp", status: 403 }));
    const engagement = detail({ state: "NDA_PENDING", actions: ["sign_nda"], awaiting: [{ command: "sign_nda", party: "developer" }], whose_turn: ["developer"] });
    renderWithIntl(
      <Actions
        engagementId={engagement.id}
        lockVersion={engagement.lock_version}
        items={actionItems(engagement)}
        counterpart={engagement.org_name}
        enrolled
        runImpl={run as (request: CommandRequest) => Promise<CommandOutcome>}
      />,
    );
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    expect((await screen.findByRole("alert")).textContent).toContain(en.trackerActions.partFailed);
    expect(screen.getByRole("button", { name: en.trackerActions.partReload })).toBeTruthy();
    expect(run).toHaveBeenCalledTimes(1); // the API refused it for a fresh code: nothing was signed, a reload starts again
  });
});
