import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PageTransition } from "./PageTransition";
import { SharedTitle, titleName } from "./SharedTitle";

vi.mock("next/navigation", () => ({ usePathname: () => "/dev" }));
afterEach(cleanup);

// D-67 (P25): the View Transition primitives render their content as it is where React has no <ViewTransition> (this
// runner's stable React, as a browser without the API simply swaps); a shared title's name is stable and CSS-safe.
describe("motion primitives", () => {
  it("render their content unchanged without View Transitions", () => {
    render(
      <PageTransition>
        <SharedTitle kind="idea" id="a1">
          <h1>Repayment nudges</h1>
        </SharedTitle>
      </PageTransition>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Repayment nudges" })).toBeTruthy();
  });

  it("names a title the same on its card and its page, with only name-safe characters", () => {
    expect(titleName("idea", "3f1c-77")).toBe("title-idea-3f1c-77");
    expect(titleName("problem", "a b/c")).toBe("title-problem-abc");
  });
});
