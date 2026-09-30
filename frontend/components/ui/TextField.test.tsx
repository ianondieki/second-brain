import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { controlClass } from "./Field";
import { TextField } from "./TextField";

afterEach(cleanup);

describe("TextField", () => {
  it("is a labelled text input by default, styled as a control, with the caller's classes added", () => {
    render(<TextField id="title" label="Title" className="font-mono" />);
    const input = screen.getByLabelText("Title") as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input.type).toBe("text");
    expect(input.className.split(" ")).toEqual(expect.arrayContaining([...controlClass.split(" "), "font-mono"]));
  });

  it("takes another input type and the input's own attributes", () => {
    render(<TextField id="email" label="Email" type="email" autoComplete="email" required name="email" />);
    const input = screen.getByLabelText("Email") as HTMLInputElement;
    expect([input.type, input.autocomplete, input.required, input.name]).toEqual(["email", "email", true, "email"]);
  });

  it("announces its hint and error with it", () => {
    render(<TextField id="kra" label="KRA PIN" hint="11 characters." error="This PIN is not valid." />);
    const input = screen.getByLabelText("KRA PIN");
    expect(input.getAttribute("aria-describedby")).toBe("kra-hint kra-error");
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });

  it("reports what is typed", () => {
    const onChange = vi.fn();
    render(<TextField id="name" label="Name" value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Wanjiru" } });
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
