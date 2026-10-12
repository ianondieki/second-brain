import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { dataSaverIn } from "@/lib/data-saver";
import { renderWithIntl } from "@/test/intl";

import { DataSaverSwitch } from "./DataSaverSwitch";

// P27 track F (REQ-UX-08; docs/spec/07 item 5): Settings › Profile's data-saver switch sets or clears the data-saver
// cookie at once, on this device (the server then treats it like Save-Data: on; lib/data-saver.test.ts and
// components/offline/data-saver-readers.test.tsx).

afterEach(() => {
  cleanup();
  document.cookie = "data-saver=; Path=/; Max-Age=0";
});

describe("the data-saver switch", () => {
  it("is a named switch with its one sentence, in the state the server read", () => {
    renderWithIntl(<DataSaverSwitch initial />);
    const toggle = screen.getByRole("switch", { name: "Data saver" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(document.getElementById(toggle.getAttribute("aria-describedby")!)!.textContent).toBe(
      "No photographs and the smallest images, on this device.",
    );
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0); // Save stays the page's one primary action
  });

  it("sets the cookie when turned on and clears it when turned off", () => {
    renderWithIntl(<DataSaverSwitch initial={false} />);
    const toggle = screen.getByRole("switch", { name: "Data saver" });
    expect(dataSaverIn(document.cookie)).toBe(false);
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(dataSaverIn(document.cookie)).toBe(true);
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(dataSaverIn(document.cookie)).toBe(false);
  });
});
