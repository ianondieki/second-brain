import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ShowTourAgain } from "./ShowTourAgain";
import { finishTour, TOUR_STORAGE_KEY, tourDone } from "./tour-store";

afterEach(cleanup);

describe("ShowTourAgain", () => {
  it("forgets a finished tour and says so", () => {
    finishTour();
    expect(tourDone()).toBe(true);
    renderWithIntl(<ShowTourAgain />);
    fireEvent.click(screen.getByRole("button", { name: "Show the tour again" }));
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBeNull();
    expect(tourDone()).toBe(false);
    expect(screen.getByRole("status").textContent).toBe("The tour will show the next time you open your home.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
