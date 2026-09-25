import type { ReactNode, Ref } from "react";

import { cn } from "@/components/ui/cn";
import { CheckIcon } from "@/components/ui/icons";

export interface Step {
  title: string;
  body?: ReactNode;
}

export interface StepsProps {
  label: string;
  /** Visually hidden suffix for finished steps ("done"). */
  doneLabel: string;
  steps: Step[];
  /** 1-based index of the current step (aria-current="step"). */
  current: number;
  /** How many steps are finished (default: all before the current one). */
  done?: number;
  /** Receives the current step's heading, so a phase change can move focus to it. */
  currentHeadingRef?: Ref<HTMLHeadingElement>;
}

/** The setup stepper (docs/spec/07 item 6): an ordered list, the current step marked with aria-current="step". */
export function Steps({ label, doneLabel, steps, current, done = current - 1, currentHeadingRef }: StepsProps) {
  return (
    <ol aria-label={label} className="flex flex-col">
      {steps.map((step, index) => {
        const n = index + 1;
        const isCurrent = n === current;
        const isDone = n <= done && !isCurrent;
        return (
          <li
            key={step.title}
            aria-current={isCurrent ? "step" : undefined}
            className="relative grid grid-cols-[2rem_minmax(0,1fr)] gap-x-4 pb-8 last:pb-0"
          >
            {n < steps.length ? (
              // The rail between one step marker and the next.
              <span aria-hidden="true" className="absolute top-9 bottom-1 left-[calc(1rem-0.5px)] w-px bg-line" />
            ) : null}
            <span
              aria-hidden="true"
              className={cn(
                "relative flex size-8 items-center justify-center rounded-full text-sm font-semibold",
                isCurrent && "bg-jacaranda text-on-accent",
                isDone && "bg-ok text-on-ok",
                !isCurrent && !isDone && "border border-ink-soft bg-paper text-ink-soft",
              )}
            >
              {isDone ? <CheckIcon className="size-5" /> : n}
            </span>
            <div className="flex min-w-0 flex-col gap-4 pt-1">
              <h3
                ref={isCurrent ? currentHeadingRef : undefined}
                tabIndex={isCurrent ? -1 : undefined}
                className={cn("text-base focus:outline-none", isCurrent ? "text-ink" : "text-ink-soft")}
              >
                {step.title}
                {isDone ? <span className="sr-only"> ({doneLabel})</span> : null}
              </h3>
              {step.body}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
