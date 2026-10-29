import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { cn } from "@/components/ui/cn";
import { controlClass, Field } from "@/components/ui/Field";

// The Team forms' text input and select, written over ui/Field here rather than taken from ui/TextField and
// ui/SelectField: those two sit in the idea editor's own chunk, and a second route importing them made Turbopack split
// that chunk, about 0.7 KB more of gzipped JS on the editor's routes (the P28 review's BLOCKER 1, measured). Same
// markup and look as theirs.

export function TeamTextInput({
  id,
  label,
  hint,
  error,
  className,
  type = "text",
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
}) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => <input type={type} className={cn(controlClass, className)} {...control} {...rest} />}
    </Field>
  );
}

export function TeamSelect({
  id,
  label,
  className,
  children,
  ...rest
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & { id: string; label: ReactNode; children: ReactNode }) {
  return (
    <Field id={id} label={label}>
      {(control) => (
        <select className={cn(controlClass, "cursor-pointer pr-8", className)} {...control} {...rest}>
          {children}
        </select>
      )}
    </Field>
  );
}
