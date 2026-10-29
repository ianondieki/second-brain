import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox } from "./Checkbox";

afterEach(cleanup);

// REQ-CON-01 (docs/spec/10): consents start unticked; the whole row is the tap target.
describe("Checkbox", () => {
  it("starts unticked, and a press anywhere on its 44 px row ticks it", () => {
    const onChange = vi.fn();
    render(<Checkbox id="marketing" name="marketing" label="Product news by email" onChange={onChange} />);
    const box = screen.getByRole("checkbox", { name: "Product news by email" }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    const row = box.closest("label")!;
    expect(row.className.split(" ")).toEqual(expect.arrayContaining(["min-h-11", "cursor-pointer"]));
    fireEvent.click(screen.getByText("Product news by email"));
    expect(box.checked).toBe(true);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("shows an error above the row and ties it to the box", () => {
    render(<Checkbox id="terms" label="I accept the terms" error="Accept the terms to continue." />);
    const box = screen.getByRole("checkbox", { name: "I accept the terms" });
    expect(box.getAttribute("aria-describedby")).toBe("terms-error");
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const error = document.getElementById("terms-error")!;
    expect(error.textContent).toBe("Accept the terms to continue.");
    expect(error.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("has no description or invalid state without an error, and follows a controlled value", () => {
    const { rerender } = render(<Checkbox id="r" label="Reminders" checked={false} onChange={() => undefined} />);
    const box = screen.getByRole("checkbox", { name: "Reminders" }) as HTMLInputElement;
    expect(box.hasAttribute("aria-describedby")).toBe(false);
    expect(box.hasAttribute("aria-invalid")).toBe(false);
    rerender(<Checkbox id="r" label="Reminders" checked onChange={() => undefined} />);
    expect(box.checked).toBe(true);
  });
});
