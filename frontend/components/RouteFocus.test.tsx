import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const route = vi.hoisted(() => ({ pathname: "/dev" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));

import { RouteFocus } from "./RouteFocus";

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function page(title: string) {
  return (
    <main id="main" tabIndex={-1}>
      <h1>{title}</h1>
      <a href="/x">Somewhere</a>
    </main>
  );
}

// P16-B ux-review (for C1): after a client navigation focus fell to <body>.
describe("RouteFocus", () => {
  it("leaves focus alone on the first load", () => {
    route.pathname = "/dev";
    render(
      <>
        {page("Home")}
        <RouteFocus />
      </>,
    );
    expect(document.activeElement).toBe(document.body);
  });

  it("moves focus to the new page's h1 once after a navigation, without a ring", () => {
    route.pathname = "/dev";
    const { rerender } = render(
      <>
        {page("Home")}
        <RouteFocus />
      </>,
    );
    route.pathname = "/dev/discover";
    rerender(
      <>
        {page("Discover")}
        <RouteFocus />
      </>,
    );
    const h1 = document.querySelector("h1")!;
    expect(document.activeElement).toBe(h1);
    expect(h1.getAttribute("tabindex")).toBe("-1");
    expect(h1.className).toContain("focus:outline-none");
    // A later render of the same page does not take focus back.
    (document.querySelector("a") as HTMLElement).focus();
    rerender(
      <>
        {page("Discover")}
        <RouteFocus />
      </>,
    );
    expect(document.activeElement?.textContent).toBe("Somewhere");
  });

  it("keeps focus where the page or the tapped control holds it", () => {
    route.pathname = "/dev";
    const { rerender } = render(
      <>
        {page("Home")}
        <RouteFocus />
      </>,
    );
    (document.querySelector("a") as HTMLElement).focus();
    route.pathname = "/dev/ideas";
    rerender(
      <>
        {page("My ideas")}
        <RouteFocus />
      </>,
    );
    expect(document.activeElement?.textContent).toBe("Somewhere");
  });

  it("falls back to <main> when the page has no h1", () => {
    route.pathname = "/a";
    const { rerender } = render(
      <>
        <main id="main" tabIndex={-1} />
        <RouteFocus />
      </>,
    );
    route.pathname = "/b";
    rerender(
      <>
        <main id="main" tabIndex={-1} />
        <RouteFocus />
      </>,
    );
    expect(document.activeElement?.id).toBe("main");
  });
});
