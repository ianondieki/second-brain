import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Avatar, initialsOf } from "./Avatar";

afterEach(cleanup);

describe("Avatar", () => {
  it.each([
    ["Achieng Otieno", "AO"],
    ["Telco A (fixture)", "TA"],
    ["Wanjiru", "W"],
    ["  ", "?"],
    ["Kenya Towers Ltd", "KT"],
  ])("takes the initials of %s as %s", (name, initials) => {
    expect(initialsOf(name)).toBe(initials);
  });

  it("is decorative beside a name, round for a person, square for an organisation, ringed when active", () => {
    const { container } = render(
      <>
        <Avatar name="Achieng Otieno" />
        <Avatar name="Telco A" kind="org" active />
      </>,
    );
    const [person, org] = container.querySelectorAll("[data-avatar]");
    expect(person.getAttribute("aria-hidden")).toBe("true");
    expect(person.className).toContain("rounded-full");
    expect(org.className).toContain("rounded-control");
    expect(org.className).toContain("ring-2");
    expect(org.textContent).toBe("TA");
  });

  it("carries the name itself when nothing beside it does", () => {
    const { getByRole } = render(<Avatar name="Achieng Otieno" labelled />);
    expect(getByRole("img", { name: "Achieng Otieno" })).toBeTruthy();
  });
});
