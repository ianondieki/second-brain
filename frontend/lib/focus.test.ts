import { afterEach, describe, expect, it } from "vitest";

import { focusPageTitle } from "./focus";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("focusPageTitle", () => {
  it("focuses the page's h1, making it focusable without a ring", () => {
    document.body.innerHTML = '<main id="main" tabindex="-1"><h1>Home</h1></main>';
    focusPageTitle();
    const h1 = document.querySelector("h1")!;
    expect(document.activeElement).toBe(h1);
    expect(h1.getAttribute("tabindex")).toBe("-1");
    expect(h1.classList.contains("focus:outline-none")).toBe(true);
  });

  it("falls back to <main> when the page has no h1", () => {
    document.body.innerHTML = '<main id="main" tabindex="-1"><p>Nothing</p></main>';
    focusPageTitle();
    expect(document.activeElement).toBe(document.getElementById("main"));
  });
});
