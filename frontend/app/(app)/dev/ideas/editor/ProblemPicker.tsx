"use client";

import { Suspense, use, useId, useState, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Button } from "@/components/ui/Button";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { preloadable } from "@/lib/preloadable";

import { MAX_PROBLEMS, type ProblemMode } from "../ideas";
import type { ProblemPanelsProps } from "./ProblemPanels";

// The search and the new-problem fields load once they are needed, not with the page (docs/spec/07 item 5, the 150 KB
// budget): an idea that already links problems shows them as a plain list, and the search opens with "Link another
// problem".
const panelsModule = preloadable(() => import("./ProblemPanels"));
export const preloadPanels = panelsModule;

function ProblemPanels(props: ProblemPanelsProps) {
  const { ProblemPanels: Panels } = use(panelsModule());
  return <Panels {...props} />;
}

export interface ProblemPickerProps extends Omit<ProblemPanelsProps, "mode" | "errors"> {
  /** Null until the developer chooses: a new idea asks first. */
  mode: ProblemMode | null;
  errors: ProblemPanelsProps["errors"] & { problems?: ReactNode };
}

/** "Which problem does it solve?": link listed problems or describe a new one (REQ-PROP-01, AC-PROP-5). */
export function ProblemPicker({ mode, errors, ...rest }: ProblemPickerProps) {
  const t = useStrings("ideaEditor");
  const f = useStrings("ideaFields");
  const id = useId();
  const { linked, onLinked } = rest;
  // The search stays open once opened; it opens by itself while nothing is linked.
  const [browsing, setBrowsing] = useState(linked.length === 0);
  const [opened, setOpened] = useState(false);
  if (!browsing && linked.length === 0) setBrowsing(true);
  const full = linked.length >= MAX_PROBLEMS;
  const showPanels = mode === "new" || (mode === "pick" && browsing);
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
      {mode === "pick" && linked.length > 0 ? (
        <section aria-labelledby={`${id}-linked`}>
          <h3 id={`${id}-linked`} className="flex flex-wrap items-baseline gap-x-3 font-semibold text-ink">
            {t("linkedLabel")}
            <span className="text-sm font-normal text-ink-soft tabular-nums">
              {t("linkedCount", { count: linked.length, max: MAX_PROBLEMS })}
            </span>
          </h3>
          <ul className="mt-2 divide-y divide-line border-y border-line">
            {linked.map((problem) => (
              <li key={problem.id} className="flex items-start justify-between gap-3 py-2">
                <span className="min-w-0 pt-2.5 [overflow-wrap:anywhere]">
                  {problem.title}
                  {problem.source === "developer" ? (
                    <span className="ml-2 text-sm text-ink-soft">{f("developerReported")}</span>
                  ) : null}
                </span>
                <Button
                  variant="link"
                  className="shrink-0"
                  aria-label={t("unlinkName", { title: problem.title })}
                  onClick={() => onLinked(linked.filter((item) => item.id !== problem.id))}
                >
                  {t("unlink")}
                </Button>
              </li>
            ))}
          </ul>
          {browsing ? null : full ? (
            <p className="mt-3 text-sm text-ink-soft">{t("maxProblems", { max: MAX_PROBLEMS })}</p>
          ) : (
            <Button
              variant="secondary"
              className="mt-4"
              onClick={() => {
                setOpened(true);
                setBrowsing(true);
              }}
            >
              {t("linkAnother")}
            </Button>
          )}
        </section>
      ) : null}
      {mode && showPanels ? (
        <Suspense fallback={null}>
          <ProblemPanels mode={mode} errors={errors} focusSearch={opened} {...rest} />
        </Suspense>
      ) : null}
    </div>
  );
}
