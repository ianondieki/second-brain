import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TextAreaField } from "./TextAreaField";

afterEach(cleanup);

describe("TextAreaField", () => {
  it("is a labelled multi-line box, four rows by default, that grows with its content", () => {
    render(<TextAreaField id="summary" label="Summary" />);
    const box = screen.getByLabelText("Summary") as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.rows).toBe(4);
    expect(box.className.split(" ")).toEqual(
      expect.arrayContaining(["[field-sizing:content]", "min-h-28", "max-h-[28rem]", "text-base"]),
    );
    expect(box.hasAttribute("aria-describedby")).toBe(false);
    expect(box.hasAttribute("aria-invalid")).toBe(false);
  });

  it("reads its hint, error and meter with it, in that order, and shows the meter under the box", () => {
    render(
      <TextAreaField
        id="approach"
        label="Approach"
        hint="Kept confidential."
        error="Write at least 20 words."
        meter="12 of 300 words"
        rows={8}
      />,
    );
    const box = screen.getByLabelText("Approach") as HTMLTextAreaElement;
    expect(box.rows).toBe(8);
    expect(box.getAttribute("aria-describedby")).toBe("approach-hint approach-error approach-meter");
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const meter = document.getElementById("approach-meter")!;
    expect(meter.textContent).toBe("12 of 300 words");
    expect(meter.className).toContain("tabular-nums");
    expect(box.compareDocumentPosition(meter) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("reads a meter alone when there is no hint or error", () => {
    render(<TextAreaField id="note" label="Note" meter="0 of 50 words" className="font-mono" />);
    const box = screen.getByLabelText("Note");
    expect(box.getAttribute("aria-describedby")).toBe("note-meter");
    expect(box.className).toContain("font-mono");
  });
});
