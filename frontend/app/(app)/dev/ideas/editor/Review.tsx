"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";

import {
  FIELD_STEP,
  nicheLabel,
  type AttestationText,
  type EditorState,
  type FieldIssue,
  type NicheNode,
  type Step,
} from "../ideas";
import type { PublishProblem } from "../outcomes";
import { FIELD_LABEL, useIssueMessage } from "./issues";

export interface ReviewProps {
  state: EditorState;
  niches: NicheNode[];
  attachments: number;
  links: number;
  /** What the screen found missing, once a publish was attempted. */
  checklist: FieldIssue[];
  /** What the API refused (the sanitiser, 422 cannot_publish). */
  issues: FieldIssue[];
  text: AttestationText;
  confirmed: Record<string, boolean>;
  showUnconfirmed: boolean;
  onConfirm: (key: string, value: boolean) => void;
  onGoTo: (step: Step) => void;
  publishing: { kind: "idle" | "busy" | "checklist" } | { kind: "failed"; problem: PublishProblem; limit?: number };
}

/**
 * Step 3: the public teaser as others will see it, a count of the confidential details, anything that still stops
 * publishing (each with a way back to its step), and the three ownership statements from GET
 * /api/proposals/attestations, shown verbatim (docs/spec/06 6.4 item 7).
 */
export function Review(props: ReviewProps) {
  const { state, text, confirmed, publishing } = props;
  const t = useTranslations("ideaEditor");
  const f = useTranslations("ideaFields");
  const issueMessage = useIssueMessage();
  const id = useId();
  const sections = (["approach", "architecture", "pricing", "notes"] as const).filter((k) => state[k].trim()).length;
  const niche = nicheLabel(props.niches, state.nicheId);

  // One entry per field: the API's finding first, else the screen's.
  const blocking: FieldIssue[] = [];
  for (const issue of [...props.issues, ...props.checklist]) {
    if (!blocking.some((b) => b.field === issue.field)) blocking.push(issue);
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby={`${id}-teaser`}>
        <h3 id={`${id}-teaser`} className="font-semibold text-ink">
          {f("teaserTitle")}
        </h3>
        <p className="mt-1 text-sm text-ink-soft">{f("teaserHint")}</p>
        <div className="mt-3 border-t border-line pt-4">
          <p className="text-lg font-semibold [overflow-wrap:anywhere] text-ink">
            {state.title.trim() || <span className="text-ink-soft">{f("notGiven")}</span>}
          </p>
          {niche ? <p className="text-sm text-ink-soft">{niche}</p> : null}
          {state.summary.trim() ? (
            <p className="mt-2 whitespace-pre-line [overflow-wrap:anywhere] text-ink">{state.summary}</p>
          ) : null}
        </div>
      </section>

      <section aria-labelledby={`${id}-details`}>
        <h3 id={`${id}-details`} className="font-semibold text-ink">
          {f("confidentialTitle")}
        </h3>
        <ul className="mt-2 flex flex-col gap-0.5 text-ink">
          <li>{t("detailsSections", { count: sections })}</li>
          <li>{t("detailsFiles", { count: props.attachments })}</li>
          <li>{t("detailsLinks", { count: props.links })}</li>
        </ul>
      </section>

      {blocking.length > 0 ? (
        <section aria-labelledby={`${id}-missing`} className="border-l-4 border-error pl-4">
          <h3 id={`${id}-missing`} className="font-semibold text-error">
            {t("missingTitle")}
          </h3>
          <ul className="mt-2 flex flex-col">
            {blocking.map((issue) => (
              <li key={issue.field} className="flex flex-wrap items-center justify-between gap-x-4">
                <span className="py-1 text-ink">
                  {t("fieldIssue", { field: f(FIELD_LABEL[issue.field]), problem: issueMessage(issue) })}
                </span>
                <Button variant="link" onClick={() => props.onGoTo(FIELD_STEP[issue.field])}>
                  {t("fixIn", { step: FIELD_STEP[issue.field] })}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <fieldset className="flex flex-col gap-1">
        <legend className="font-semibold text-ink">{t("attestationsTitle")}</legend>
        <p className="mb-2 text-sm text-ink-soft">{t("publishLead")}</p>
        {text.statements.map((statement) => (
          <Checkbox
            key={`${text.version}-${statement.key}`}
            id={`${id}-attest-${statement.key}`}
            label={statement.text}
            checked={Boolean(confirmed[statement.key])}
            error={props.showUnconfirmed && !confirmed[statement.key] ? t("attestationRequired") : undefined}
            onChange={(event) => props.onConfirm(statement.key, event.target.checked)}
          />
        ))}
      </fieldset>

      {publishing.kind === "failed" ? (
        <Alert>
          {publishing.problem === "planLimit"
            ? publishing.limit !== undefined
              ? t("problem.planLimit", { limit: publishing.limit })
              : t("problem.planLimitUnknown")
            : t(`problem.${publishing.problem}`)}
        </Alert>
      ) : null}
    </div>
  );
}
