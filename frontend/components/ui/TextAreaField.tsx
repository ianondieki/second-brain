import type { ReactNode, TextareaHTMLAttributes } from "react";

import { cn } from "./cn";
import { Field } from "./Field";

export interface TextAreaFieldProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  /** Shown under the box (for example a word count) and read with the field, not on every keystroke. */
  meter?: ReactNode;
}

/** A labelled multi-line input, styled like the text inputs; it grows with its content where the browser can. */
export function TextAreaField({ id, label, hint, error, meter, className, rows = 4, ...rest }: TextAreaFieldProps) {
  const meterId = meter ? `${id}-meter` : undefined;
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {({ "aria-describedby": describedBy, ...control }) => (
        <>
          <textarea
            rows={rows}
            className={cn(
              "min-h-28 w-full min-w-0 rounded-control border border-ink-soft bg-field px-3 py-2.5 text-base text-ink",
              "[field-sizing:content] max-h-[28rem]",
              // A growing box keeps its last line clear of the fixed tab bar under 1024 px.
              "scroll-mb-28 lg:scroll-mb-6",
              "aria-invalid:border-error aria-invalid:shadow-[inset_0_0_0_1px_var(--error)]",
              className,
            )}
            aria-describedby={[describedBy, meterId].filter(Boolean).join(" ") || undefined}
            {...control}
            {...rest}
          />
          {meter ? (
            <p id={meterId} className="text-sm text-ink-soft tabular-nums">
              {meter}
            </p>
          ) : null}
        </>
      )}
    </Field>
  );
}
