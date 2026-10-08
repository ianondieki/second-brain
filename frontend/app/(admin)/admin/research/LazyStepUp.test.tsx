import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
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
  it("holds focus while it loads, says it could not be fetched with Try again focused and Cancel back, then tries again", async () => {
    const { LazyStepUp } = await import("./LazyStepUp");
    const cancel = vi.fn();
    renderWithIntl(<LazyStepUp onConfirmed={() => undefined} onCancel={cancel} />);
    expect(document.activeElement?.hasAttribute("data-step-up-loading")).toBe(true);
    expect((await screen.findByRole("alert")).textContent).toContain("That did not work. Check your connection and try again.");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Try again" })));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledOnce();
    load.fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Code from your app")).toBeTruthy();
  });
});
