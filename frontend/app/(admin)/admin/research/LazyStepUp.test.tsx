import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

// P25 (REQ-UX-05, the coordinator's rule for lazy chunks): the fresh-code form is fetched when asked for; a failed
// fetch shows the generic sentence and "Try again", which fetches it again.
const load = vi.hoisted(() => ({ fail: true }));
vi.mock("./StepUp", async (original) => {
  if (load.fail) throw new Error("offline");
  return original();
});

afterEach(cleanup);

describe("LazyStepUp", () => {
  it("says it could not be fetched, then tries again", async () => {
    const { LazyStepUp } = await import("./LazyStepUp");
    renderWithIntl(<LazyStepUp onConfirmed={() => undefined} />);
    expect((await screen.findByRole("alert")).textContent).toContain("That did not work. Check your connection and try again.");
    load.fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Code from your app")).toBeTruthy();
  });
});
