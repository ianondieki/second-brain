import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ConfirmDialog, openConfirm } from "./ConfirmDialog";

beforeAll(() => {
  // jsdom implements <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(cleanup);

function Harness({
  tone,
  onConfirm = () => {},
  busy = false,
  confirmDisabled = false,
}: {
  tone?: "primary" | "danger";
  onConfirm?: () => void;
  busy?: boolean;
  confirmDisabled?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [closed, setClosed] = useState(0);
  return (
    <>
      <button type="button" onClick={() => openConfirm(ref.current)}>
        Delete idea
      </button>
      <p data-closed={closed} />
      <ConfirmDialog
        ref={ref}
        title="Delete this idea?"
        confirmLabel="Delete"
        busyLabel="Deleting…"
        cancelLabel="Keep it"
        tone={tone}
        busy={busy}
        confirmDisabled={confirmDisabled}
        onConfirm={onConfirm}
        onClose={() => setClosed((n) => n + 1)}
      >
        <p>Its certificates are kept.</p>
      </ConfirmDialog>
    </>
  );
}

const dialog = () => screen.getByRole("dialog", { hidden: true }) as HTMLDialogElement;

// P16 design system, Confirmations: a native modal <dialog> named by its title and described by its body; the confirm
// button names the action; Cancel (focused first) and Escape change nothing; focus goes back to the opener.
describe("ConfirmDialog", () => {
  it("opens as a named, described dialog with focus on Cancel", () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Delete idea" });
    trigger.focus();
    fireEvent.click(trigger);
    const box = screen.getByRole("dialog", { name: "Delete this idea?" });
    expect(box.getAttribute("aria-describedby")).toBe(within(box).getByText("Its certificates are kept.").parentElement!.id);
    expect(document.activeElement?.textContent).toBe("Keep it");
    expect(box.className.split(" ")).toEqual(
      expect.arrayContaining(["rounded-panel", "shadow-overlay", "backdrop:bg-scrim"]),
    );
  });

  it("names the action on its button and runs it once", () => {
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("styles its main button as primary or danger but never marks it as the screen's primary action", () => {
    const { rerender } = render(<Harness tone="primary" />);
    const confirm = () => within(dialog()).getByRole("button", { name: "Delete", hidden: true });
    expect(confirm().className).toContain("bg-jacaranda");
    rerender(<Harness tone="danger" />);
    expect(confirm().className.split(" ")).toEqual(expect.arrayContaining(["text-error", "border-error"]));
    expect(confirm().className).not.toMatch(/(^|\s)bg-error(\s|$)/);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("closes on Cancel, tells its owner, and gives focus back to the opener", () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Delete idea" });
    trigger.focus();
    fireEvent.click(trigger);
    act(() => {
      fireEvent.click(within(dialog()).getByRole("button", { name: "Keep it" }));
    });
    expect(dialog().open).toBe(false);
    expect(document.querySelector("[data-closed]")?.getAttribute("data-closed")).toBe("1");
    expect(document.activeElement).toBe(trigger);
  });

  it("lets Escape cancel, except while the action runs: then Escape and Cancel wait", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(<Harness onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    const idle = new Event("cancel", { cancelable: true });
    dialog().dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);

    rerender(<Harness onConfirm={onConfirm} busy />);
    const busy = new Event("cancel", { cancelable: true });
    dialog().dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);
    fireEvent.click(within(dialog()).getByRole("button", { name: "Keep it" }));
    expect(dialog().open).toBe(true);
    const confirm = within(dialog()).getByRole("button", { name: "Deleting…" });
    expect(confirm.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("ignores the confirm button while what it needs has not loaded", () => {
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} confirmDisabled />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    fireEvent.click(within(dialog()).getByRole("button", { name: "Delete" }));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
