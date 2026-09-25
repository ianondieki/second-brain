"use client";

import { useState, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";
import { controlClass, Field } from "./Field";
import { EyeIcon, EyeOffIcon } from "./icons";

export interface PasswordFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Visible text of the toggle ("Show" / "Hide") and its fuller accessible names. */
  showLabel: string;
  hideLabel: string;
  showName: string;
  hideName: string;
}

/** Password input with a show/hide toggle (a real button, 44 px target, name contains its visible text). */
export function PasswordField({
  id,
  label,
  hint,
  error,
  showLabel,
  hideLabel,
  showName,
  hideName,
  className,
  ...rest
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => (
        <div className="relative">
          <input
            type={visible ? "text" : "password"}
            className={cn(controlClass, "pr-24", className)}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            {...control}
            {...rest}
          />
          <button
            type="button"
            aria-controls={id}
            aria-label={visible ? hideName : showName}
            onClick={() => setVisible((v) => !v)}
            className={
              "absolute inset-y-0.5 right-0.5 inline-flex min-w-11 items-center gap-1.5 rounded-[8px] px-3 " +
              "text-sm font-semibold text-jacaranda hover:bg-jacaranda-wash"
            }
          >
            {visible ? <EyeOffIcon className="size-5" /> : <EyeIcon className="size-5" />}
            <span>{visible ? hideLabel : showLabel}</span>
          </button>
        </div>
      )}
    </Field>
  );
}
