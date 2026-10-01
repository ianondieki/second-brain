import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RadioGroup, type RadioOption } from "./RadioGroup";

afterEach(cleanup);

type Side = "developer" | "org";
const OPTIONS: ReadonlyArray<RadioOption<Side>> = [
  { value: "developer", label: "I build solutions", hint: "Publish proposals and pitch them." },
  { value: "org", label: "I represent an organisation" },
];

describe("RadioGroup", () => {
  it("is a fieldset named by its legend, one full-width row per option, sharing one name", () => {
    render(<RadioGroup id="side" name="side" legend="Who are you?" options={OPTIONS} value={null} onChange={vi.fn()} />);
    const group = screen.getByRole("group", { name: "Who are you?" });
    const radios = within(group).getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((r) => [r.id, r.name, r.value, r.checked])).toEqual([
      ["side-developer", "side", "developer", false],
      ["side-org", "side", "org", false],
    ]);
    const row = radios[0].closest("label")!;
    expect(row.className.split(" ")).toEqual(expect.arrayContaining(["min-h-14", "has-checked:bg-accent-wash"]));
    expect(screen.getByRole("radio", { name: /I represent an organisation/ })).toBe(radios[1]);
  });

  it("ties an option's hint to its radio, and only that one", () => {
    render(<RadioGroup id="side" name="side" legend="Who are you?" options={OPTIONS} value={null} onChange={vi.fn()} />);
    const [developer, org] = screen.getAllByRole("radio");
    expect(developer.getAttribute("aria-describedby")).toBe("side-developer-hint");
    expect(document.getElementById("side-developer-hint")?.textContent).toBe("Publish proposals and pitch them.");
    expect(org.hasAttribute("aria-describedby")).toBe(false);
  });

  it("checks the chosen value and reports a new choice", () => {
    const onChange = vi.fn();
    render(<RadioGroup id="side" name="side" legend="Who are you?" options={OPTIONS} value="org" onChange={onChange} />);
    const [developer, org] = screen.getAllByRole("radio") as HTMLInputElement[];
    expect([developer.checked, org.checked]).toEqual([false, true]);
    fireEvent.click(screen.getByText("I build solutions"));
    expect(onChange).toHaveBeenCalledWith("developer");
  });

  it("announces an error through the fieldset (radios take no aria-invalid)", () => {
    render(
      <RadioGroup
        id="side"
        name="side"
        legend="Who are you?"
        options={OPTIONS}
        value={null}
        onChange={vi.fn()}
        error="Choose one."
      />,
    );
    const group = screen.getByRole("group", { name: "Who are you?" });
    expect(group.getAttribute("aria-describedby")).toBe("side-error");
    expect(document.getElementById("side-error")?.textContent).toBe("Choose one.");
    for (const radio of screen.getAllByRole("radio")) expect(radio.hasAttribute("aria-invalid")).toBe(false);
  });
});
