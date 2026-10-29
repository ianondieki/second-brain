"use client";

import { useStrings } from "@/components/ClientStrings";
import { CheckIcon } from "@/components/ui/status-icons";
import { cn } from "@/components/ui/cn";

import { STEPS, type Step } from "../ideas";

/**
 * The three steps as an ordered list with aria-current="step" on the current one (docs/spec/07 item 6): a numbered
 * mark, a connector and the step's name, in the tracker's timeline language (D-52). Every step is a button: the
 * editor saves as it goes, so any step can be opened in any order.
 */
export function Stepper({ step, onStep, disabled = false }: { step: Step; onStep: (step: Step) => void; disabled?: boolean }) {
  const t = useStrings("ideaEditor");
  return (
    <nav aria-label={t("stepsLabel")}>
      <ol className="grid grid-cols-3">
        {STEPS.map((item, index) => {
          const current = item === step;
          const done = item < step;
          const last = index === STEPS.length - 1;
          return (
            <li key={item} className="relative min-w-0">
              {last ? null : (
                <span aria-hidden="true" className={cn("absolute top-[15px] right-0 left-9 h-0.5", done ? "bg-accent" : "bg-line")} />
              )}
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                disabled={disabled}
                onClick={() => onStep(item)}
                className={cn(
                  "relative flex min-h-11 w-full flex-col items-start gap-2 pr-3 text-left text-sm",
                  current ? "font-semibold text-ink" : "font-medium text-ink-soft",
                  !current && "hover:text-ink",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex size-8 items-center justify-center rounded-full border-2 text-sm font-semibold tabular-nums",
                    current ? "border-accent bg-accent text-on-accent" : done ? "border-accent bg-accent-wash text-accent" : "border-line bg-paper text-ink-soft",
                  )}
                >
                  {done ? <CheckIcon className="size-4" /> : index + 1}
                </span>
                <span className="sr-only">{t("stepCount", { current: item, total: STEPS.length })}</span>
                <span className="leading-snug [overflow-wrap:normal] hyphens-none">{t(`step${item}`)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
