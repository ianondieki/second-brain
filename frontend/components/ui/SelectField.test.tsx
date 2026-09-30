import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { controlClass } from "./Field";
import { SelectField } from "./SelectField";

afterEach(cleanup);

describe("SelectField", () => {
  it("is a labelled native select, styled like the text inputs, with room for the arrow", () => {
    render(
      <SelectField id="county" label="County" className="max-w-xs" defaultValue="KE-30">
        <option value="KE-47">Nairobi</option>
        <option value="KE-30">Kisumu</option>
      </SelectField>,
    );
    const select = screen.getByLabelText("County") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("KE-30");
    expect([...select.options].map((o) => o.textContent)).toEqual(["Nairobi", "Kisumu"]);
    expect(select.className.split(" ")).toEqual(
      expect.arrayContaining([...controlClass.split(" "), "cursor-pointer", "pr-8", "max-w-xs"]),
    );
  });

  it("announces its hint and error with it and reports a choice", () => {
    const onChange = vi.fn();
    render(
      <SelectField id="kind" label="Kind" hint="Pick one." error="Choose a kind." value="" onChange={onChange}>
        <option value="">Choose</option>
        <option value="company">Company</option>
      </SelectField>,
    );
    const select = screen.getByLabelText("Kind");
    expect(select.getAttribute("aria-describedby")).toBe("kind-hint kind-error");
    expect(select.getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(select, { target: { value: "company" } });
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
