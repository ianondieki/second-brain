import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ShowTourAgain } from "./ShowTourAgain";
import { finishTour, tourDone, tourStorageKey } from "./tour-store";

afterEach(cleanup);

describe("ShowTourAgain", () => {
  it("forgets a finished tour of its side and says so", () => {
    finishTour("developer");
    finishTour("org");
    expect(document.cookie).toContain("wazo-tour-developer=done");
    renderWithIntl(<ShowTourAgain side="developer" />);
    fireEvent.click(screen.getByRole("button", { name: "Show the tour again" }));
    expect(window.localStorage.getItem(tourStorageKey("developer"))).toBeNull();
    expect(document.cookie).not.toContain("wazo-tour-developer=done"); // the server would otherwise keep hiding it
    expect(tourDone("developer")).toBe(false);
    expect(tourDone("org")).toBe(true); // the other side's tour is its own memory
    expect(screen.getByRole("status").textContent).toBe("The tour will show the next time you open your home.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
