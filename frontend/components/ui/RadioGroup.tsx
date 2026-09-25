import type { ReactNode } from "react";

import { FieldError } from "./Field";

export interface RadioOption<V extends string> {
  value: V;
  label: ReactNode;
  hint?: ReactNode;
}

export interface RadioGroupProps<V extends string> {
  id: string;
  name: string;
  legend: ReactNode;
  options: ReadonlyArray<RadioOption<V>>;
  value: V | null;
  onChange: (value: V) => void;
  error?: ReactNode;
}

/** A fieldset of full-width radio rows (at least 56 px tall); the selected row takes the jacaranda wash. */
export function RadioGroup<V extends string>({ id, name, legend, options, value, onChange, error }: RadioGroupProps<V>) {
  const errorId = error ? `${id}-error` : undefined;
  return (
    <fieldset id={id} aria-describedby={errorId} className="flex flex-col gap-2">
      <legend className="mb-2 font-medium text-ink">{legend}</legend>
      {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      {options.map((option) => {
        const optionId = `${id}-${option.value}`;
        const hintId = option.hint ? `${optionId}-hint` : undefined;
        return (
          <label
            key={option.value}
            htmlFor={optionId}
            className={
              "flex min-h-14 cursor-pointer items-start gap-3 rounded-control border border-ink-soft bg-field " +
              "px-4 py-3 has-checked:border-jacaranda has-checked:bg-jacaranda-wash " +
              "has-checked:shadow-[inset_0_0_0_1px_var(--jacaranda)] " +
              "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-jacaranda"
            }
          >
            <input
              id={optionId}
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              aria-describedby={hintId}
              aria-invalid={error ? true : undefined}
              className="mt-0.5 size-5 shrink-0 cursor-pointer accent-jacaranda focus-visible:outline-none"
            />
            <span className="flex flex-col">
              <span className="font-semibold text-ink">{option.label}</span>
              {option.hint ? (
                <span id={hintId} className="text-sm text-ink-soft">
                  {option.hint}
                </span>
              ) : null}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
