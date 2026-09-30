import { cleanup, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Alert } from "./Alert";
import { noticeIconTone } from "./notice";
import { AlertIcon, CheckIcon, InfoIcon } from "./status-icons";

afterEach(cleanup);

// The announced notice (its roles and tone washes are Callout.test.tsx's): the icon that goes with each tone, and the
// focus a form moves to it after a refusal.
function pathsOf(element: Element | null): string[] {
  return [...(element?.querySelectorAll("path") ?? [])].map((path) => path.getAttribute("d") ?? "");
}

describe("Alert", () => {
  it("is an error by default, announced at once", () => {
    render(<Alert>That code did not work.</Alert>);
    expect(screen.getByRole("alert").textContent).toBe("That code did not work.");
  });

  it.each([
    ["error", AlertIcon],
    ["ok", CheckIcon],
    ["info", InfoIcon],
  ] as const)("draws the %s icon in the tone's colour, decorative", (tone, Icon) => {
    const { container } = render(<Alert tone={tone}>Words</Alert>);
    const icon = container.querySelector("svg")!;
    const expected = render(<Icon />).container.querySelector("svg");
    expect(pathsOf(icon)).toEqual(pathsOf(expected));
    expect(icon.getAttribute("aria-hidden")).toBe("true");
    expect(icon.getAttribute("class")?.split(" ")).toContain(noticeIconTone[tone]);
  });

  it("can take focus from a form (tabIndex -1, a ref) without joining the tab order", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <Alert ref={ref} className="mt-4">
        Check the highlighted fields.
      </Alert>,
    );
    const alert = screen.getByRole("alert");
    expect(ref.current).toBe(alert);
    expect(alert.tabIndex).toBe(-1);
    expect(alert.className.split(" ")).toContain("mt-4");
    ref.current!.focus();
    expect(document.activeElement).toBe(alert);
  });
});
