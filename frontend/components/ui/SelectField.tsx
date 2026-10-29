import type { ReactNode, SelectHTMLAttributes } from "react";

import { cn } from "./cn";
import { controlClass, Field } from "./Field";

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}

/** A native select (the platform picker is the best one on a phone), styled like the text inputs. */
export function SelectField({ id, label, hint, error, className, children, ...rest }: SelectFieldProps) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {(control) => (
        <select className={cn(controlClass, "cursor-pointer pr-8", className)} {...control} {...rest}>
          {children}
        </select>
      )}
    </Field>
  );
}
