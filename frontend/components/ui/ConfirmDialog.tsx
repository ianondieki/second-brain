"use client";

import { useId, type ReactNode, type RefObject } from "react";

import { Button, buttonClass } from "./Button";
import { cn } from "./cn";

export interface ConfirmDialogProps {
  /** The native <dialog>: open it with `openConfirm(ref.current)`, close it with `ref.current.close()`. */
  ref: RefObject<HTMLDialogElement | null>;
  title: ReactNode;
  /** What happens if the person goes ahead, said before anything does. */
  children: ReactNode;
  /** The confirm button names the action ("Withdraw", "Delete"), never "OK". */
  confirmLabel: string;
  /** The confirm button's words while the action runs ("Withdrawing…"). */
  busyLabel: string;
  busy?: boolean;
  /** The confirm button ignores presses (aria-disabled) until something it needs has loaded. */
  confirmDisabled?: boolean;
  onConfirm: () => void;
  /** primary: the dialog's main button looks like a primary one; danger: destructive, outlined in the error colour. */
  tone?: "primary" | "danger";
  cancelLabel: string;
  /** Why the action did not happen (an Alert), shown above the buttons. */
  problem?: ReactNode;
  /** The dialog closed (Cancel, Escape, or its owner closing it). */
  onClose?: () => void;
  /** Wider for longer wording (the assistant's consent text). */
  size?: "md" | "lg";
  /** Attributes for the body's wrapper (for example the consent version the wording belongs to). */
  bodyProps?: { [key: `data-${string}`]: string | undefined; className?: string };
}

// The control that had focus when each dialog opened, to give it back on close.
const openers = new WeakMap<HTMLDialogElement, HTMLElement>();

/** Opens a ConfirmDialog as a modal and puts focus on Cancel, the choice that changes nothing. */
export function openConfirm(dialog: HTMLDialogElement | null) {
  if (!dialog || dialog.open) return;
  const opener = document.activeElement;
  if (opener instanceof HTMLElement && opener !== document.body) openers.set(dialog, opener);
  dialog.showModal();
  dialog.querySelector<HTMLElement>("[data-dialog-cancel]")?.focus();
}

/**
 * A confirmation for a destructive or irreversible step only (docs/platform/design/p16-design-system.md,
 * Confirmations): a native modal <dialog>, which traps focus, makes the page behind it inert, closes on Escape and
 * gives focus back to the control that opened it. The one elevation (shadow-overlay) over the one scrim. Its main
 * button is styled, not marked, as primary: the screen's data-primary stays on the page's own action. While the step
 * runs, Escape and Cancel wait for its answer.
 */
export function ConfirmDialog({
  ref,
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  confirmDisabled = false,
  onConfirm,
  tone = "primary",
  cancelLabel,
  problem,
  onClose,
  size = "md",
  bodyProps,
}: ConfirmDialogProps) {
  const titleId = useId();
  const bodyId = useId();
  const blocked = busy || confirmDisabled;
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
      onClose={(event) => {
        // Browsers give focus back to the opener as a modal dialog closes; where focus was left nowhere (or inside
        // the closed dialog), this does. A step that moved focus on purpose (to a heading) keeps it.
        const node = event.currentTarget;
        const opener = openers.get(node);
        openers.delete(node);
        const active = document.activeElement;
        if (opener?.isConnected && (!active || active === document.body || node.contains(active))) opener.focus();
        onClose?.();
      }}
      className={cn(
        "m-auto w-[calc(100%-2rem)] rounded-panel border border-line bg-paper p-6 text-ink shadow-overlay",
        "backdrop:bg-scrim",
        size === "lg" ? "max-w-lg" : "max-w-md",
      )}
    >
      <h2 id={titleId} className="text-lg text-ink">
        {title}
      </h2>
      <div id={bodyId} {...bodyProps} className={cn("mt-3 [overflow-wrap:anywhere] text-ink", bodyProps?.className)}>
        {children}
      </div>
      {problem ? <div className="mt-4">{problem}</div> : null}
      {/* Cancel first, on top on phones and on the left from 640 px: the visual order is the focus order. */}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
        <Button variant="secondary" busy={busy} onClick={() => ref.current?.close()} data-dialog-cancel="">
          {cancelLabel}
        </Button>
        <button
          type="button"
          onClick={() => {
            if (!blocked) onConfirm();
          }}
          aria-disabled={blocked || undefined}
          data-dialog-confirm=""
          className={buttonClass(tone)}
        >
          {busy ? busyLabel : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
