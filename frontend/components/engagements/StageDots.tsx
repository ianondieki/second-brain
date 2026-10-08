import { useTranslations } from "next-intl";

import { GROUPS, stepperSteps, type Summary } from "@/components/tracker/model";

/**
 * Where an engagement stands as five dots on a line (P25, D-67): the tracker's five stages, done ones filled, the current
 * one ringed in bloom (in the error colour past its deadline, hollow while paused or ended), the rest open. One image
 * with its words ("Stage 3 of 5: Agreement"); the stage's chip beside it says the state in words too.
 */
export function StageDots({ item }: { item: Pick<Summary, "state" | "stage_group" | "due" | "paused_from" | "stage_label"> }) {
  const t = useTranslations("engagementCard");
  const steps = stepperSteps({ state: item.state, stage_group: item.stage_group, due: item.due, paused_from: item.paused_from });
  const current = Math.max(
    0,
    steps.findIndex((s) => s.chip !== "completed" && s.chip !== "pending"),
  );
  const at = item.state === "CLOSED" ? GROUPS.length : current + 1;
  return (
    <p
      role="img"
      aria-label={t("stageOf", { step: at, total: GROUPS.length, stage: item.stage_label })}
      className="stage-dots"
      data-stage-dots={at}
    >
      {steps.map((step) => (
        <span key={step.group} aria-hidden="true" data-dot={step.chip} />
      ))}
    </p>
  );
}
