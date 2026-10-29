import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { standaloneLinkClass } from "./Button";
import { StandaloneLink } from "./StandaloneLink";

afterEach(cleanup);

describe("StandaloneLink", () => {
  it("is an in-app link on its own 44 px line, with the pending hint under the words at a fixed place", () => {
    render(<StandaloneLink href="/problems/7">Start a proposal from this problem</StandaloneLink>);
    const link = screen.getByRole("link", { name: "Start a proposal from this problem" });
    expect(link.getAttribute("href")).toBe("/problems/7");
    expect(link.className.split(" ")).toEqual([...standaloneLinkClass.split(" "), "relative"]);
    const hint = link.querySelector("[data-link-pending]")!;
    expect(hint.className.split(" ")).toEqual(expect.arrayContaining(["absolute", "bottom-0.5", "left-0"]));
    expect(hint.getAttribute("aria-hidden")).toBe("true");
  });

  it("passes the caller's class and link attributes through", () => {
    render(
      <StandaloneLink href="/dev/ideas?cursor=2" className="self-end" rel="next" aria-label="Next page">
        Next
      </StandaloneLink>,
    );
    const link = screen.getByRole("link", { name: "Next page" });
    expect(link.className.split(" ")).toContain("self-end");
    expect(link.getAttribute("rel")).toBe("next");
    expect(link.getAttribute("href")).toBe("/dev/ideas?cursor=2");
  });
});
