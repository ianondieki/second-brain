import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LoadingScreen } from "./LoadingScreen";

afterEach(cleanup);

// docs/spec/07 (states): a route's loading state says so to assistive technology and draws no spinner.
describe("LoadingScreen", () => {
  it("is a busy status region that says Loading, with decorative bars only", () => {
    const { container } = render(<LoadingScreen label="Loading…" />);
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-busy")).toBe("true");
    expect(status.textContent).toContain("Loading…");
    expect(container.querySelectorAll(".loading-bar").length).toBeGreaterThanOrEqual(3);
    expect(container.querySelector("[aria-hidden='true'] .loading-bar")).not.toBeNull();
    expect(container.querySelector("[data-lattice]")).not.toBeNull();
  });
});
