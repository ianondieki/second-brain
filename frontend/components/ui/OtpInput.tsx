"use client";

import type { ClipboardEvent, InputHTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";
import { controlClass, Field } from "./Field";

/** Keeps the digits of `raw` (so "123 456" and "123-456" both become "123456"), at most `length` of them. */
export function normaliseCode(raw: string, length: number): string {
  return raw.replace(/\D/g, "").slice(0, length);
}

export interface OtpInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "value" | "onChange" | "type" | "onPaste"> {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  length?: number;
}

/**
 * One input for a one-time code: numeric keypad, the platform's one-time-code autofill, and paste of a whole code
 * with spaces or dashes (docs/spec/07 item 6: OTP pasteable). A pasted full code replaces what was typed.
 */
export function OtpInput({ id, label, hint, error, value, onChange, length = 6, className, ...rest }: OtpInputProps) {
  function handlePaste(event: ClipboardEvent<HTMLInputElement>) {
    const digits = normaliseCode(event.clipboardData.getData("text"), length);
    if (digits.length === length) {
      event.preventDefault();
      onChange(digits);
    }
  }
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => (
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          spellCheck={false}
          value={value}
          onChange={(event) => onChange(normaliseCode(event.target.value, length))}
          onPaste={handlePaste}
          className={cn(controlClass, "code-figures max-w-[12rem] text-lg font-semibold", className)}
          {...control}
          {...rest}
        />
      )}
    </Field>
  );
}
