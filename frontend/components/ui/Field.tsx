import type { ReactNode } from "react";

import { cn } from "./cn";
import { AlertIcon } from "./icons";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
}

export interface FieldProps {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  /** Renders the control with the ids that tie it to its hint and error (aria-describedby). */
  children: (control: FieldControlProps) => ReactNode;
}

/** Label, optional hint, optional error and the control, in that reading order (error text sits by the field). */
export function Field({ id, label, hint, error, className, children }: FieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="font-medium text-ink">
        {label}
      </label>
      {hint ? (
        <p id={hintId} className="text-sm text-ink-soft">
          {hint}
        </p>
      ) : null}
      {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
    </div>
  );
}

export function FieldError({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="flex items-start gap-1.5 text-sm font-medium text-error">
      <AlertIcon className="mt-px size-5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** Shared look of text inputs and selects: 48 px tall, 16 px text (no zoom on iOS), ink-soft border for 3:1. */
export const controlClass =
  "h-12 w-full min-w-0 rounded-control border border-ink-soft bg-field px-3 text-base text-ink " +
  "aria-invalid:border-error aria-invalid:shadow-[inset_0_0_0_1px_var(--error)]";
