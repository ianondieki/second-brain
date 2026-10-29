import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Overflow } from "./Overflow";
import { closeOverflows } from "./overflow-close";

// REQ-DEV-03 (P22-CF review): an overflow menu closes on Escape (focus back to its button), on a press outside, and
// when one of its items is pressed (focus to its button, where a dialog it opens gives focus back).

beforeEach(() => {
  document.addEventListener("click", closeOverflows);
  document.addEventListener("keydown", closeOverflows);
});
afterEach(() => {
  document.removeEventListener("click", closeOverflows);
  document.removeEventListener("keydown", closeOverflows);
  cleanup();
});

function open() {
  render(
    <>
      <p>Outside</p>
      <Overflow label="More options" align="end">
        <button type="button">Block</button>
      </Overflow>
    </>,
  );
  const menu = document.querySelector("details") as HTMLDetailsElement;
  menu.open = true;
  return { menu, summary: menu.querySelector("summary") as HTMLElement, item: menu.querySelector("button") as HTMLElement };
}

describe("the overflow menu", () => {
  it("opens leftward when aligned to the end", () => {
    const { menu } = open();
    expect(menu.querySelector("div")?.className).toContain("right-0");
  });

  it("closes on Escape and gives focus back to its button", () => {
    const { menu, summary, item } = open();
    item.focus();
    fireEvent.keyDown(item, { key: "Escape" });
    expect(menu.open).toBe(false);
    expect(document.activeElement).toBe(summary);
  });

  it("closes on a press outside, not on a press inside that is not an item", () => {
    const { menu } = open();
    fireEvent.click(menu.querySelector("div") as HTMLElement);
    expect(menu.open).toBe(true);
    fireEvent.click(document.querySelector("p") as HTMLElement);
    expect(menu.open).toBe(false);
  });

  it("closes when an item is pressed, with focus on its button", () => {
    const { menu, summary, item } = open();
    fireEvent.click(item);
    expect(menu.open).toBe(false);
    expect(document.activeElement).toBe(summary);
  });
});
