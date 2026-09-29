"use client";

import { useTranslations } from "next-intl";
import { lazy, Suspense, useId, type ReactNode } from "react";

import { RadioGroup } from "@/components/ui/RadioGroup";

import type { ProblemMode } from "../ideas";
import type { ProblemPanelsProps } from "./ProblemPanels";

// The picker and the new-problem fields load once a choice is made (docs/spec/07 item 5, the 150 KB budget).
const ProblemPanels = lazy(() => import("./ProblemPanels").then((m) => ({ default: m.ProblemPanels })));

export interface ProblemPickerProps extends Omit<ProblemPanelsProps, "mode" | "errors"> {
  /** Null until the developer chooses: a new idea asks first. */
  mode: ProblemMode | null;
  errors: ProblemPanelsProps["errors"] & { problems?: ReactNode };
}

/** "Which problem does it solve?": link listed problems or describe a new one (REQ-PROP-01, AC-PROP-5). */
export function ProblemPicker({ mode, errors, ...rest }: ProblemPickerProps) {
  const t = useTranslations("ideaEditor");
  const id = useId();
  return (
    <div className="flex flex-col gap-5">
      <RadioGroup<ProblemMode>
        id={`${id}-mode`}
        name="problem-mode"
        legend={t("problemLegend")}
        value={mode}
        onChange={rest.onMode}
        error={mode === "new" ? undefined : errors.problems}
        options={[
          { value: "pick", label: t("pickOption"), hint: t("pickHint") },
          { value: "new", label: t("newOption"), hint: t("newHint") },
        ]}
      />
      {mode ? (
        <Suspense fallback={null}>
          <ProblemPanels mode={mode} errors={errors} {...rest} />
        </Suspense>
      ) : null}
    </div>
  );
}
