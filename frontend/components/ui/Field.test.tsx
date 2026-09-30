import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { controlClass, Field, FieldError } from "./Field";

afterEach(cleanup);

// P16 design system, Forms: label, optional hint, optional error, then the control, in that reading order; the hint
// and the error are tied to the control through aria-describedby, so a screen reader reads them with it.
describe("Field", () => {
  it("labels the control and reads label, hint, error and control in that order", () => {
    const { container } = render(
      <Field id="org-name" label="Organisation name" hint="As registered with BRS." error="Enter a name.">
        {(control) => <input {...control} />}
      </Field>,
    );
    const input = screen.getByLabelText("Organisation name");
    expect(input.id).toBe("org-name");
    expect(input.getAttribute("aria-describedby")).toBe("org-name-hint org-name-error");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById("org-name-hint")?.textContent).toBe("As registered with BRS.");
    expect(document.getElementById("org-name-error")?.textContent).toBe("Enter a name.");
    const order = [...container.firstElementChild!.children].map((el) => el.tagName + (el.id ? `#${el.id}` : ""));
    expect(order).toEqual(["LABEL", "P#org-name-hint", "P#org-name-error", "INPUT#org-name"]);
  });

  it("describes the control by the hint alone, or by nothing, and marks it invalid only with an error", () => {
    render(
      <>
        <Field id="with-hint" label="Website" hint="Starts with https://">
          {(control) => <input {...control} />}
        </Field>
        <Field id="bare" label="Phone">
          {(control) => <input {...control} />}
        </Field>
      </>,
    );
    const hinted = screen.getByLabelText("Website");
    expect(hinted.getAttribute("aria-describedby")).toBe("with-hint-hint");
    expect(hinted.hasAttribute("aria-invalid")).toBe(false);
    const bare = screen.getByLabelText("Phone");
    expect(bare.hasAttribute("aria-describedby")).toBe(false);
    expect(bare.hasAttribute("aria-invalid")).toBe(false);
    expect(document.getElementById("bare-error")).toBeNull();
  });

  it("shows an error as an icon and words in the error colour, the icon hidden from assistive tech", () => {
    const { container } = render(<FieldError id="e1">Choose a county.</FieldError>);
    const error = container.firstElementChild!;
    expect(error.id).toBe("e1");
    expect(error.className).toContain("text-error");
    expect(error.textContent).toBe("Choose a county.");
    expect(error.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("styles controls 48 px tall with 16 px text (no zoom on focus in iOS) and an error outline when invalid", () => {
    const classes = controlClass.split(" ");
    expect(classes).toEqual(expect.arrayContaining(["h-12", "text-base", "w-full", "aria-invalid:border-error"]));
  });
});
