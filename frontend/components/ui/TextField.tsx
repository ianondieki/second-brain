import type { InputHTMLAttributes, ReactNode } from "react";

import { cn } from "./cn";
import { controlClass, Field } from "./Field";

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
}

/** A labelled text input; the hint and error are announced with it through aria-describedby. */
export function TextField({ id, label, hint, error, className, type = "text", ...rest }: TextFieldProps) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => <input type={type} className={cn(controlClass, className)} {...control} {...rest} />}
    </Field>
  );
}
