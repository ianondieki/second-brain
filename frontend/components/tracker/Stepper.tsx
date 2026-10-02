import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { cn } from "@/components/ui/cn";

import { CHIP_TONE, ChipMark } from "./Chip";
import type { Step } from "./model";

/**
 * The 5-group stepper (docs/spec/06 6.9 Rendering; docs/spec/07 item 6): an ordered list whose current group carries
 * aria-current="step". Vertical under 1024 px, a horizontal spine from 1024 px. Each group shows its mark, name and
 * status word; the current group also shows the stage's own label and what is due (`detail`).
 */
export function Stepper({ steps, detail, actor }: { steps: Step[]; detail?: ReactNode; /** Who acts now (an Avatar), shown with the current step. */ actor?: ReactNode }) {
  const t = useTranslations("tracker");
  const currentIndex = steps.findIndex((s) => s.chip !== "completed" && s.chip !== "pending");
  return (
    <ol aria-label={t("stepperLabel")} data-stepper="" className="flex flex-col lg:grid lg:grid-cols-5 lg:gap-0">
      {steps.map((step, i) => {
        const current = i === currentIndex;
        const last = i === steps.length - 1;
        return (
          <li
            key={step.group}
            aria-current={current ? "step" : undefined}
            data-group={step.group}
            data-state={step.chip}
            className="relative flex gap-3 pb-6 last:pb-0 lg:flex-col lg:gap-2 lg:pr-3 lg:pb-0"
          >
            {last ? null : (
              <span
                aria-hidden="true"
                className={cn(
                  "absolute top-7 bottom-1 left-[11px] w-0.5 rounded-full",
                  "lg:top-[11px] lg:right-2 lg:bottom-auto lg:left-9 lg:h-0.5 lg:w-auto",
                  step.chip === "completed" ? "bg-ok" : "bg-line",
                )}
              />
            )}
            <ChipMark kind={step.chip} className={cn("relative size-6 bg-paper", CHIP_TONE[step.chip])} />
            <div className="min-w-0 flex-1">
              {/* Group names wrap only at spaces, never inside a word ("Implementation" stays whole at every width). */}
              <p className={cn("leading-6 [overflow-wrap:normal] hyphens-none lg:text-sm", current ? "font-semibold text-ink" : "font-medium text-ink")}>
                {t(`group.${step.group}`)}
              </p>
              <p className={cn("text-sm font-semibold", CHIP_TONE[step.chip])}>{t(`chip.${step.word ?? step.chip}`)}</p>
              {current && (detail || actor) ? (
                <div className="mt-1 flex items-start gap-2 text-sm text-ink">
                  {actor ? <span className="lg:hidden">{actor}</span> : null}
                  {detail ? <div className="min-w-0">{detail}</div> : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
