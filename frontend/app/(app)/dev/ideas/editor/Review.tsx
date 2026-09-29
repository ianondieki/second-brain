"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";

import type { Calls } from "../calls";
import {
  FIELD_STEP,
  ideaHref,
  linkLines,
  nicheLabel,
  type Attestations,
  type AttestationText,
  type EditorState,
  type FieldIssue,
  type NicheNode,
  type Step,
} from "../ideas";
import type { PublishProblem, SaveProblem } from "../outcomes";
import { useIssueMessage } from "./issues";

export interface ReviewProps {
  state: EditorState;
  niches: NicheNode[];
  attachments: number;
  /** What the screen finds missing (publishChecklist). */
  checklist: FieldIssue[];
  /** What the API refused (the sanitiser, 422 cannot_publish). */
  issues: FieldIssue[];
  onIssues: (issues: FieldIssue[]) => void;
  /** From the first publish attempt on, the fields show what is missing too. */
  onShowRequired: () => void;
  initialText: AttestationText;
  /** Saves everything typed (creating the draft if needed); the save's refusal, or null. */
  saveAll: () => Promise<SaveProblem | null>;
  getId: () => string | null;
  getCalls: () => Promise<Calls>;
  onGoTo: (step: Step) => void;
  /** Publishing is under way: the editor locks its stepper meanwhile. */
  onBusy: (busy: boolean) => void;
}

type Publishing =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "checklist" }
  | { kind: "failed"; problem: PublishProblem; limit?: number };

/**
 * Step 3, loaded when it opens: the public teaser as others will see it, a count of the confidential details, what
 * still stops publishing (with a way back to its step), the three ownership statements from GET
 * /api/proposals/attestations shown verbatim (docs/spec/06 6.4 item 7), and Publish, the step's one primary action.
 */
export function Review(props: ReviewProps) {
  const { state } = props;
  const t = useStrings("ideaEditor");
  const f = useStrings("ideaFields");
  const router = useRouter();
  const issueMessage = useIssueMessage();
  const id = useId();
  const [text, setText] = useState(props.initialText);
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [publishing, setPublishing] = useState<Publishing>({ kind: "idle" });
  const alert = useRef<HTMLDivElement>(null);
  const busy = publishing.kind === "busy";
  const { onBusy } = props;

  // A refusal or a checklist is announced (role="alert") and takes focus, so the reason is where the reader is.
  useEffect(() => {
    if (publishing.kind === "checklist" || publishing.kind === "failed") alert.current?.focus();
    onBusy(publishing.kind === "busy");
  }, [publishing, onBusy]);

  const keys = text.statements.map((s) => s.key);
  const attempted = publishing.kind !== "idle";
  const sections = (["approach", "architecture", "pricing", "notes"] as const).filter((k) => state[k].trim()).length;
  const niche = nicheLabel(props.niches, state.nicheId);

  // One entry per field: the API's finding first, else the screen's.
  const blocking: FieldIssue[] = [];
  for (const issue of [...props.issues, ...(attempted ? props.checklist : [])]) {
    if (!blocking.some((b) => b.field === issue.field)) blocking.push(issue);
  }
  const steps = [...new Set(blocking.map((issue) => FIELD_STEP[issue.field]))].sort();

  async function publish() {
    if (publishing.kind === "busy") return;
    props.onShowRequired();
    if (props.checklist.length > 0 || !keys.every((key) => confirmed[key])) {
      setPublishing({ kind: "checklist" });
      return;
    }
    setPublishing({ kind: "busy" });
    const saveProblem = await props.saveAll();
    const proposalId = props.getId();
    if (saveProblem || !proposalId) {
      const problem = !saveProblem || saveProblem === "validation" ? "failed" : saveProblem;
      setPublishing({ kind: "failed", problem });
      return;
    }
    const calls = await props.getCalls().catch(() => null);
    if (!calls) {
      setPublishing({ kind: "failed", problem: "network" });
      return;
    }
    const attestations = Object.fromEntries(keys.map((key) => [key, true])) as unknown as Attestations;
    const outcome = await calls.publish(proposalId, text, attestations);
    if (outcome.ok) {
      router.push(`${ideaHref(proposalId)}?published=1`);
      return;
    }
    if (outcome.fields.length > 0) props.onIssues(outcome.fields);
    if (outcome.problem === "attestationsChanged") {
      const fresh = await calls.attestationText();
      if (fresh.ok) setText(fresh.value);
      setConfirmed({});
    }
    setPublishing({ kind: "failed", problem: outcome.problem, limit: outcome.limit });
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
          <li>{t("detailsLinks", { count: linkLines(state.links).length })}</li>
        </ul>
      </section>

      {blocking.length > 0 ? (
        <section aria-labelledby={`${id}-missing`} className="border-l-4 border-error pl-4">
          <h3 id={`${id}-missing`} className="font-semibold text-error">
            {t("missingTitle")}
          </h3>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-ink marker:text-ink-soft">
            {blocking.map((issue) => (
              <li key={issue.field}>{issueMessage(issue)}</li>
            ))}
          </ul>
          {/* One way back per step that has something to fix. */}
          <ul className="mt-2 flex flex-wrap gap-x-6">
            {steps.map((step) => (
              <li key={step}>
                <Button variant="link" onClick={() => props.onGoTo(step)}>
                  {t("fixIn", { step })}
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
            error={attempted && !confirmed[statement.key] ? t("attestationRequired") : undefined}
            disabled={busy}
            onChange={(event) => setConfirmed((current) => ({ ...current, [statement.key]: event.target.checked }))}
          />
        ))}
      </fieldset>

      {publishing.kind === "checklist" ? (
        <Alert ref={alert}>{blocking.length > 0 ? t("problem.checklist") : t("problem.attestationsRequired")}</Alert>
      ) : null}
      {publishing.kind === "failed" ? (
        <Alert ref={alert}>
          {publishing.problem === "planLimit"
            ? publishing.limit !== undefined
              ? t("problem.planLimit", { limit: publishing.limit })
              : t("problem.planLimitUnknown")
            : t(`problem.${publishing.problem}`)}
        </Alert>
      ) : null}

      <div className="flex flex-col-reverse gap-3 border-t border-line pt-6 sm:flex-row sm:items-center sm:justify-between">
        <Button variant="secondary" busy={busy} onClick={() => props.onGoTo(2)}>
          {t("back")}
        </Button>
        <Button variant="primary" busy={publishing.kind === "busy"} onClick={() => void publish()}>
          {publishing.kind === "busy" ? t("publishing") : t("publish")}
        </Button>
      </div>
    </div>
  );
}
