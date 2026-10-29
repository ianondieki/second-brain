import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { normaliseCode, OtpInput } from "./OtpInput";

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <OtpInput id="code" label="6-digit code" value={value} onChange={setValue} />;
}

afterEach(cleanup);

describe("normaliseCode", () => {
  it("keeps digits only, up to the code length", () => {
    expect(normaliseCode("123 456", 6)).toBe("123456");
    expect(normaliseCode("123-456", 6)).toBe("123456");
    expect(normaliseCode(" 12a34 5678", 6)).toBe("123456");
    expect(normaliseCode("", 6)).toBe("");
  });
});

describe("OtpInput", () => {
  it("is a labelled numeric one-time-code field", () => {
    render(<Harness />);
    const input = screen.getByLabelText("6-digit code");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
  });

  it("accepts a pasted code with a space in it", () => {
    render(<Harness />);
    const input = screen.getByLabelText<HTMLInputElement>("6-digit code");
    fireEvent.paste(input, { clipboardData: { getData: () => "123 456" } });
    expect(input.value).toBe("123456");
  });

  it("replaces partly typed digits when a whole code is pasted", () => {
    render(<Harness initial="12" />);
    const input = screen.getByLabelText<HTMLInputElement>("6-digit code");
    fireEvent.paste(input, { clipboardData: { getData: () => "987-654" } });
    expect(input.value).toBe("987654");
  });

  it("drops letters and extra digits as they are typed", () => {
    render(<Harness />);
    const input = screen.getByLabelText<HTMLInputElement>("6-digit code");
    fireEvent.change(input, { target: { value: "12ab34567" } });
    expect(input.value).toBe("123456");
  });

  it("ties its error message to the input", () => {
    render(<OtpInput id="code" label="6-digit code" value="" onChange={() => {}} error="Enter the code." />);
    const input = screen.getByLabelText("6-digit code");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe("code-error");
    expect(document.getElementById("code-error")?.textContent).toBe("Enter the code.");
  });
});
