"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";

import { STEPS, type Step } from "../ideas";

/**
 * The three steps as an ordered list with aria-current="step" on the current one (docs/spec/07 item 6). Every step
 * is a button: the editor saves as it goes, so any step can be opened in any order.
 */
export function Stepper({ step, onStep, disabled = false }: { step: Step; onStep: (step: Step) => void; disabled?: boolean }) {
  const t = useTranslations("ideaEditor");
  return (
    <nav aria-label={t("stepsLabel")}>
      <ol className="grid grid-cols-3 gap-2">
        {STEPS.map((item) => {
          const current = item === step;
          const done = item < step;
          return (
            <li key={item} className="min-w-0">
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                disabled={disabled}
                onClick={() => onStep(item)}
                className={cn(
                  "flex min-h-11 w-full flex-col items-start gap-1.5 border-t-4 pt-2 text-left text-sm",
                  current ? "border-jacaranda font-semibold text-ink" : "border-line font-medium text-ink-soft",
                  done && "border-[color-mix(in_oklab,var(--jacaranda)_45%,var(--paper))]",
                  !current && "hover:text-ink",
                )}
              >
                <span className="tabular-nums">{t("stepCount", { current: item, total: STEPS.length })}</span>
                <span className={cn("leading-snug", current ? "text-ink" : undefined)}>{t(`step${item}`)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
