import type { InputHTMLAttributes, ReactNode } from "react";

import { FieldError } from "./Field";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> {
  id: string;
  label: ReactNode;
  error?: ReactNode;
}

/**
 * A checkbox whose whole row (at least 44 px tall) toggles it. Never pre-ticked by this component: consents start
 * unticked (docs/spec/10, REQ-CON-01).
 */
export function Checkbox({ id, label, error, ...rest }: CheckboxProps) {
  const errorId = error ? `${id}-error` : undefined;
  return (
    <div className="flex flex-col gap-1">
      {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      <label htmlFor={id} className="flex min-h-11 cursor-pointer items-start gap-3 py-2.5">
        <input
          id={id}
          type="checkbox"
          className="mt-0.5 size-5 shrink-0 cursor-pointer accent-jacaranda"
          aria-describedby={errorId}
          aria-invalid={error ? true : undefined}
          {...rest}
        />
        <span className="text-ink">{label}</span>
      </label>
    </div>
  );
}
