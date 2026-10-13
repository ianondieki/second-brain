import { useTranslations } from "next-intl";
import type { CSSProperties, ReactNode } from "react";

import { cn } from "@/components/ui/cn";
import type en from "@/locales/en.json";

import { CHIP_TONE, ChipMark } from "./Chip";
import type { ChipKind, Step, SubStage } from "./model";

/**
 * The 5-group stepper (docs/spec/06 6.9 Rendering; docs/spec/07 item 6): an ordered list whose current group carries
 * aria-current="step". Vertical under 1024 px, a horizontal spine from 1024 px. Each group shows its mark, name and
 * status word; the current group also shows the stage's own label and what is due (`detail`). The done part of the line
 * draws once and the current mark breathes three times (P25), both still under reduced motion.
 */
export function Stepper({
  steps,
  detail,
  actor,
  stages,
}: {
  steps: Step[];
  detail?: ReactNode;
  /** Who acts now (an Avatar), shown with the current step. */
  actor?: ReactNode;
  /**
   * The current group's own stages (SubStageList): under the current step on phones; from 1024 px a row under the
   * spine starting at the current column (the spec's detail panel), so the narrow column keeps its short lines.
   */
  stages?: (layout: "column" | "row") => ReactNode;
}) {
  const t = useTranslations("tracker");
  const currentIndex = steps.findIndex((s) => s.chip !== "completed" && s.chip !== "pending");
  const row = stages && currentIndex >= 0 ? stages("row") : null;
  return (
    <>
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
            className="relative flex gap-3.5 pb-7 last:pb-0 lg:flex-col lg:gap-3 lg:pr-4 lg:pb-0"
          >
            {last ? null : (
              <span
                aria-hidden="true"
                // The done part of the line draws once, step after step (globals.css .step-line; still under reduced motion).
                data-step-line={step.chip === "completed" ? "done" : undefined}
                style={{ "--i": i } as CSSProperties}
                className={cn(
                  "step-line absolute top-8 bottom-1.5 left-[11px] w-0.5 rounded-full",
                  "lg:top-[11px] lg:right-1.5 lg:bottom-auto lg:left-9 lg:h-0.5 lg:w-auto",
                  step.chip === "completed" ? "bg-accent" : "bg-line",
                )}
              />
            )}
            {/* Done and current in bloom; the current step wears a petal halo, so it reads as "here" at a glance. */}
            <ChipMark
              kind={step.chip}
              className={cn("relative size-6 rounded-full bg-paper", STEP_TONE[step.chip], current && "step-breathe ring-[5px] ring-accent-wash")}
            />
            <div className="min-w-0 flex-1">
              {/* Group names wrap only at spaces, never inside a word ("Implementation" stays whole at every width). */}
              <p
                className={cn(
                  "leading-6 [overflow-wrap:normal] hyphens-none",
                  current ? "font-bold text-ink" : step.chip === "pending" ? "font-medium text-ink-soft" : "font-semibold text-ink",
                )}
              >
                {t(`group.${step.group}`)}
              </p>
              <p className={cn("text-sm", current ? "font-bold" : "font-medium", WORD_TONE[step.chip])}>{t(`chip.${step.word ?? step.chip}`)}</p>
              {current && (detail || actor) ? (
                <div className="mt-2 flex items-start gap-2 text-sm text-ink">
                  {actor ? <span className="lg:hidden">{actor}</span> : null}
                  {detail ? <div className="min-w-0">{detail}</div> : null}
                </div>
              ) : null}
              {current && stages ? <div className="lg:hidden">{stages("column")}</div> : null}
            </div>
          </li>
        );
      })}
    </ol>
    {row ? (
      <div data-substages-row="" className="mt-5 hidden lg:grid lg:grid-cols-5">
        <div style={{ gridColumn: `${currentIndex + 1} / -1` }} className="border-t border-line pt-4 pr-4">
          {row}
        </div>
      </div>
    ) : null}
    </>
  );
}

/** The marks: bloom for done and current; pending recedes; the side states keep their own tones (Chip's). */
const STEP_TONE: Record<ChipKind, string> = { ...CHIP_TONE, completed: "text-accent" };

/** The status words: done recedes to ink-soft beside its bloom mark; the current word is bloom. */
const WORD_TONE: Record<ChipKind, string> = { ...CHIP_TONE, completed: "text-ink-soft" };

type StageKey = `stage.${keyof (typeof en)["tracker"]["stage"]}`;
/** The `tracker` namespace's translator, on the server (getTranslations) or in a server render (useTranslations). */
type StageNames = ((key: StageKey) => string) & { has: (key: StageKey) => boolean };

/**
 * A stage's name in the reader's language (`tracker.stage.<STATE>`, the API's STAGE_LABELS translated), or the API's
 * own label (English) for a stage the locales do not name. Server-side only: the names never join the client bundle.
 */
export function stageName(t: StageNames, state: string, label: string): string {
  const key = `stage.${state}` as StageKey;
  return t.has(key) ? t(key) : label;
}

/**
 * The current group's own stages under its name (docs/spec/06 6.9: "sub-stages collapsed except the current group"),
 * from the API's `steps`: so a public entity's Contact and NDA lists its procurement route (3b) and a private
 * organisation's never does (AC-TRACK-5). Each stage's mark goes with its status word for screen readers; the stage it
 * stands at wears the group's own chip (on hold, waiting for an answer, overdue). Labels come from the locales
 * (`tracker.stage.<STATE>`), the API's English label only for a stage they do not name. Server-rendered: none of it
 * joins the client's JavaScript.
 */
export function SubStageList({
  stages,
  group,
  layout = "column",
}: {
  stages: SubStage[];
  group: Step["group"];
  /** A column under the current step (phones), or a wrapping row (the desktop panel). */
  layout?: "column" | "row";
}) {
  const t = useTranslations("tracker");
  if (stages.length === 0) return null;
  const name = (stage: SubStage) => stageName(t, stage.state, stage.label);
  return (
    <ol
      aria-label={t("subStages", { group: t(`group.${group}`) })}
      data-substages={layout}
      className={layout === "row" ? "flex flex-wrap gap-x-6 gap-y-2" : "mt-3 ml-0.5 flex flex-col gap-1.5"}
    >
      {stages.map((stage) => {
        const done = stage.mark === "completed";
        const pending = stage.mark === "pending";
        // Where the engagement stands: its word shows too (mark, words and colour; docs/spec/07 item 6).
        const here = !done && !pending;
        const tone = stage.mark === "current" ? "text-accent" : CHIP_TONE[stage.mark];
        return (
          <li
            key={stage.state}
            data-substage={stage.state}
            data-state={stage.mark}
            className={cn(
              "flex items-start gap-2 text-sm",
              layout === "row" && "whitespace-nowrap",
              done || pending ? "text-ink-soft" : "font-semibold text-ink",
            )}
          >
            <ChipMark
              kind={stage.mark}
              className={cn("mt-0.5 size-3.5", pending ? "text-ink-soft" : done ? "text-accent" : tone)}
            />
            <span aria-hidden="true" className="min-w-0">
              {name(stage)}
              {here ? (
                <span data-substage-word="" className={cn("ml-2 font-medium whitespace-nowrap", tone)}>
                  {t(`chip.${stage.word ?? stage.mark}`)}
                </span>
              ) : null}
            </span>
            <span className="sr-only">{t("subStage", { stage: name(stage), state: t(`chip.${stage.word ?? stage.mark}`) })}</span>
          </li>
        );
      })}
    </ol>
  );
}
