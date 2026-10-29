import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY } from "@/lib/theme";
import { renderWithIntl } from "@/test/intl";

import { ThemeToggle } from "./ThemeToggle";

afterEach(cleanup);
beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("ThemeToggle", () => {
  it("is a labelled radio group with system, light and dark, system checked by default", () => {
    renderWithIntl(<ThemeToggle />);
    expect(screen.getByRole("group", { name: "Appearance" })).toBeTruthy();
    expect(screen.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["system", "light", "dark"]);
    expect((screen.getByRole("radio", { name: "System" }) as HTMLInputElement).checked).toBe(true);
  });

  it("applies and remembers a choice at once", () => {
    renderWithIntl(<ThemeToggle />);
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect((screen.getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
  });
});
