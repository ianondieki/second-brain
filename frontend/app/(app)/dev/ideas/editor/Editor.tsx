"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon, LockIcon } from "@/components/ui/icons";
import { SelectField } from "@/components/ui/SelectField";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";
import { useHydrated } from "@/lib/hooks/useHydrated";

import { attestationText, publish, saveDraft } from "../calls";
import {
  ASKS,
  draftBody,
  editHref,
  ideaHref,
  LIMITS,
  linkLines,
  linksProblem,
  MATURITIES,
  MATURITY_KEY,
  MAX_SUMMARY_WORDS,
  publishChecklist,
  wordCount,
  type Attachment,
  type Attestations,
  type AttestationText,
  type County,
  type EditorState,
  type FieldIssue,
  type FieldName,
  type NicheNode,
  type ProblemCard,
  type Step,
} from "../ideas";
import type { PublishProblem, SaveProblem } from "../outcomes";
import { Attachments } from "./Attachments";
import { useIssueMessage } from "./issues";
import { ProblemPicker } from "./ProblemPicker";
import { Review } from "./Review";
import { Stepper } from "./Stepper";

export interface EditorProps {
  /** The proposal's id; null for a new idea (the first save creates it). */
  id: string | null;
  initial: EditorState;
  attachments: Attachment[];
  step: Step;
  niches: NicheNode[];
  counties: County[];
  attestations: AttestationText;
  problems: ProblemCard[];
  calls?: { saveDraft: typeof saveDraft; publish: typeof publish; attestationText: typeof attestationText };
}

type Save =
  | { kind: "clean" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved"; partial: boolean }
  | { kind: "failed"; problem: SaveProblem };

type PublishState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "checklist" }
  | { kind: "failed"; problem: PublishProblem; limit?: number };

const AUTOSAVE_MS = 1200;
const DEFAULT_CALLS = { saveDraft, publish, attestationText };

/** Which fields each state key feeds, so an edit clears the API's issue on that field. */
const FIELD_OF: Partial<Record<keyof EditorState, FieldName>> = {
  title: "title",
  nicheId: "niche_id",
  countyCode: "county_code",
  maturity: "maturity",
  ask: "ask",
  problemStatement: "problem_statement",
  summary: "summary",
  impactClaims: "impact_claims",
  problems: "problems",
  newProblemTitle: "new_problem.title",
  newProblemStatement: "new_problem.statement",
  links: "links",
};

/**
 * The idea editor (REQ-PROP-01; docs/spec/06 6.1, 6.3): 1 Problem and teaser (Tier 1, public once published), 2 Full
 * details (Tier 2, confidential), 3 Review, attest and publish. Every change is saved as a draft (Tier 0, yours only)
 * a moment after typing stops; a new idea becomes a draft on its first save. Publishing is the last step's one primary
 * action; "Continue" is the others'.
 */
export function Editor(props: EditorProps) {
  const t = useTranslations("ideaEditor");
  const f = useTranslations("ideaFields");
  const router = useRouter();
  const issueMessage = useIssueMessage();
  const hydrated = useHydrated();
  const calls = props.calls ?? DEFAULT_CALLS;

  const [state, setState] = useState<EditorState>(props.initial);
  const [step, setStep] = useState<Step>(props.step);
  const [attachments, setAttachments] = useState<Attachment[]>(props.attachments);
  const [save, setSave] = useState<Save>({ kind: "clean" });
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [showRequired, setShowRequired] = useState(false);
  const [text, setText] = useState<AttestationText>(props.attestations);
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [publishing, setPublishing] = useState<PublishState>({ kind: "idle" });

  const idRef = useRef<string | null>(props.id);
  const latest = useRef(state); // what the fields hold now, read by saves that run after a render
  const edits = useRef(0); // bumped on every change
  const savedEdits = useRef(0); // the edit count the last successful save covered
  const inFlight = useRef<Promise<SaveProblem | null> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const stepRef = useRef(step);

  // Plain functions, not hooks: everything they change lives in refs, so a timer set in one render still saves what
  // the fields hold when it fires.
  function schedule(ms: number) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      void flush();
    }, ms);
  }

  /** One save of everything typed so far; null when it worked (or there was nothing new to save). */
  async function runSave(): Promise<SaveProblem | null> {
    const started = edits.current;
    if (started === savedEdits.current) return null; // nothing new (and a new idea is not created before typing)
    const creating = idRef.current === null;
    const plan = draftBody(latest.current);
    setSave({ kind: "saving" });
    const outcome = await calls.saveDraft(idRef.current, plan.body);
    if (!outcome.ok) {
      setSave({ kind: "failed", problem: outcome.problem });
      if (outcome.fields.length > 0) setIssues(outcome.fields);
      return outcome.problem;
    }
    savedEdits.current = started;
    if (creating) {
      idRef.current = outcome.value.id;
      // The address now names the draft, so a reload or the back button returns to it (no navigation, no refetch).
      window.history.replaceState(window.history.state, "", editHref(outcome.value.id, stepRef.current));
    }
    setAttachments(outcome.value.draft?.confidential.attachments ?? []);
    setIssues([]);
    if (edits.current !== started) {
      setSave({ kind: "dirty" }); // typed during the save: the next one follows shortly
      schedule(AUTOSAVE_MS);
    } else {
      setSave({ kind: "saved", partial: plan.held.length > 0 });
    }
    return null;
  }

  /** Saves now, after any save in flight (saves never overlap, so a new idea is created once). */
  function flush(): Promise<SaveProblem | null> {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const previous = inFlight.current ?? Promise.resolve(null);
    const next = previous.then(() => runSave());
    inFlight.current = next;
    void next.finally(() => {
      if (inFlight.current === next) inFlight.current = null;
    });
    return next;
  }

  function update(patch: Partial<EditorState>) {
    edits.current += 1;
    const next = { ...latest.current, ...patch };
    latest.current = next;
    setState(next);
    const touched = new Set(Object.keys(patch).map((key) => FIELD_OF[key as keyof EditorState]));
    setIssues((current) => current.filter((issue) => !touched.has(issue.field)));
    setSave({ kind: "dirty" });
    schedule(AUTOSAVE_MS);
  }

  /** Saves until nothing typed is left unsaved (someone may type while a save runs); the first refusal stops it. */
  async function saveAll(): Promise<SaveProblem | null> {
    for (let round = 0; round < 3 && edits.current !== savedEdits.current; round++) {
      const problem = await flush();
      if (problem) return problem;
    }
    return null;
  }

  // Leaving with unsaved typing asks first (the browser's own wording).
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (save.kind === "dirty" || save.kind === "saving") event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [save.kind]);

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  function goTo(next: Step) {
    void flush();
    setStep(next);
    stepRef.current = next;
    if (idRef.current) window.history.replaceState(window.history.state, "", editHref(idRef.current, next));
    // Focus the new step's heading, so keyboard and screen-reader users start at its top.
    requestAnimationFrame(() => {
      heading.current?.focus();
      heading.current?.scrollIntoView({ block: "start" });
    });
  }

  async function ensureId(): Promise<string | null> {
    if (!idRef.current) {
      edits.current += 1; // a file alone is reason enough to create the draft
      await flush();
    }
    return idRef.current;
  }

  // --- issues shown by the fields ---------------------------------------------------------------------------------

  const checklist = publishChecklist(state);
  const shown: FieldIssue[] = [
    ...issues,
    ...(showRequired ? checklist.filter((c) => !issues.some((i) => i.field === c.field)) : []),
  ];
  const errorFor = (field: FieldName) => {
    const issue = shown.find((i) => i.field === field);
    return issue ? issueMessage(issue) : undefined;
  };
  const words = wordCount(state.summary);
  const linkProblem = linksProblem(state.links);

  // --- publishing -------------------------------------------------------------------------------------------------

  const statementKeys = text.statements.map((s) => s.key);
  const allConfirmed = statementKeys.every((key) => confirmed[key]);

  async function doPublish() {
    if (publishing.kind === "busy") return;
    setShowRequired(true);
    if (checklist.length > 0 || !allConfirmed) {
      setPublishing({ kind: "checklist" });
      return;
    }
    setPublishing({ kind: "busy" });
    if (!idRef.current) edits.current += 1; // publishing straight away still needs the draft
    const saveProblem = await saveAll();
    const id = idRef.current;
    if (saveProblem || !id) {
      setPublishing({ kind: "failed", problem: saveProblem === "validation" || !saveProblem ? "failed" : saveProblem });
      return;
    }
    const attestations = Object.fromEntries(statementKeys.map((key) => [key, true])) as unknown as Attestations;
    const outcome = await calls.publish(id, text, attestations);
    if (outcome.ok) {
      router.push(`${ideaHref(id)}?published=1`);
      return;
    }
    if (outcome.fields.length > 0) setIssues(outcome.fields);
    if (outcome.problem === "attestationsChanged") {
      const fresh = await calls.attestationText();
      if (fresh.ok) setText(fresh.value);
      setConfirmed({});
    }
    setPublishing({ kind: "failed", problem: outcome.problem, limit: outcome.limit });
  }

  const statusLine = <SaveStatus save={save} onRetry={() => void flush()} />;

  return (
    // Disabled until React runs: anything typed into the server-rendered fields before then would be lost (slow
    // connections take seconds to hydrate). `data-hydrated` tells tests when the editor is live.
    <fieldset
      disabled={!hydrated}
      data-hydrated={hydrated ? "true" : "false"}
      className="m-0 flex min-w-0 flex-col gap-8 border-0 p-0"
    >
      <div className="flex flex-col gap-3">
        <Stepper step={step} onStep={goTo} />
        {statusLine}
      </div>

      <h2 ref={heading} tabIndex={-1} className="text-lg text-ink focus:outline-none lg:text-xl">
        {t(`step${step}`)}
      </h2>

      {save.kind === "failed" ? <Alert>{t(`problem.${save.problem}`)}</Alert> : null}

      {step === 1 ? (
        <div className="flex flex-col gap-10">
          <div className="flex flex-col gap-6">
            <TextField
              id="idea-title"
              label={f("title")}
              value={state.title}
              maxLength={LIMITS.title}
              error={errorFor("title")}
              onChange={(e) => update({ title: e.target.value })}
            />
            <SelectField
              id="idea-niche"
              label={f("niche")}
              value={state.nicheId}
              error={errorFor("niche_id")}
              onChange={(e) => update({ nicheId: e.target.value })}
            >
              <option value="">{t("nicheChoose")}</option>
              {props.niches.map((parent) =>
                parent.children.length > 0 ? (
                  <optgroup key={parent.id} label={parent.name}>
                    {parent.children.map((child) => (
                      <option key={child.id} value={child.id}>
                        {child.name}
                      </option>
                    ))}
                  </optgroup>
                ) : (
                  <option key={parent.id} value={parent.id}>
                    {parent.name}
                  </option>
                ),
              )}
            </SelectField>
          </div>

          <ProblemPicker
            mode={state.problemMode}
            linked={state.problems}
            newTitle={state.newProblemTitle}
            newStatement={state.newProblemStatement}
            niches={props.niches}
            initialResults={props.problems}
            errors={{
              problems: errorFor("problems"),
              newTitle: errorFor("new_problem.title"),
              newStatement: errorFor("new_problem.statement"),
            }}
            onMode={(problemMode) => update({ problemMode })}
            onLinked={(problems) => update({ problems })}
            onNewTitle={(newProblemTitle) => update({ newProblemTitle })}
            onNewStatement={(newProblemStatement) => update({ newProblemStatement })}
          />

          <section aria-labelledby="teaser-title" className="flex flex-col gap-6 border-t border-line pt-6">
            <div>
              <h3 id="teaser-title" className="font-semibold text-ink">
                {f("teaserTitle")}
              </h3>
              <p className="mt-1 text-sm text-ink-soft">{t("teaserHint")}</p>
            </div>
            <TextAreaField
              id="idea-problem-statement"
              label={f("problemStatement")}
              value={state.problemStatement}
              maxLength={LIMITS.problem_statement}
              error={errorFor("problem_statement")}
              onChange={(e) => update({ problemStatement: e.target.value })}
            />
            <TextAreaField
              id="idea-summary"
              label={f("summary")}
              hint={t("summaryHint")}
              value={state.summary}
              maxLength={LIMITS.summary}
              error={errorFor("summary")}
              meter={
                <span className={cn(words > MAX_SUMMARY_WORDS && "font-semibold text-error")}>
                  {t("wordCount", { count: words, max: MAX_SUMMARY_WORDS })}
                </span>
              }
              onChange={(e) => update({ summary: e.target.value })}
            />
            <div className="grid gap-6 sm:grid-cols-2">
              <SelectField
                id="idea-maturity"
                label={f("maturity")}
                value={state.maturity}
                error={errorFor("maturity")}
                onChange={(e) => update({ maturity: e.target.value as EditorState["maturity"] })}
              >
                <option value="">{t("maturityChoose")}</option>
                {MATURITIES.map((value) => (
                  <option key={value} value={value}>
                    {f(`maturityValue.${MATURITY_KEY[value]}`)}
                  </option>
                ))}
              </SelectField>
              <SelectField
                id="idea-ask"
                label={f("ask")}
                value={state.ask}
                error={errorFor("ask")}
                onChange={(e) => update({ ask: e.target.value as EditorState["ask"] })}
              >
                <option value="">{t("askChoose")}</option>
                {ASKS.map((value) => (
                  <option key={value} value={value}>
                    {f(`askValue.${value}`)}
                  </option>
                ))}
              </SelectField>
            </div>
            <SelectField
              id="idea-county"
              label={f("county")}
              hint={t("countyHint")}
              value={state.countyCode}
              error={errorFor("county_code")}
              onChange={(e) => update({ countyCode: e.target.value })}
            >
              <option value="">{f("anyCounty")}</option>
              {props.counties.map((county) => (
                <option key={county.code} value={county.code}>
                  {county.name}
                </option>
              ))}
            </SelectField>
            <TextAreaField
              id="idea-impact"
              label={f("impactClaims")}
              hint={t("impactHint")}
              value={state.impactClaims}
              maxLength={LIMITS.impact_claims}
              error={errorFor("impact_claims")}
              onChange={(e) => update({ impactClaims: e.target.value })}
            />
          </section>
        </div>
      ) : null}

      {step === 2 ? (
        <section aria-labelledby="details-notice" className="flex flex-col gap-6 border-l-4 border-jacaranda pl-4 sm:pl-6">
          <div>
            <p id="details-notice" className="inline-flex items-center gap-1.5 font-semibold text-jacaranda">
              <LockIcon className="size-5 shrink-0" />
              {f("confidentialBadge")}
            </p>
            <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{f("confidentialNotice")}</p>
          </div>
          {(["approach", "architecture", "pricing", "notes"] as const).map((key) => (
            <TextAreaField
              key={key}
              id={`idea-${key}`}
              label={f(key)}
              hint={t(`${key}Hint`)}
              value={state[key]}
              maxLength={LIMITS[key]}
              rows={key === "approach" || key === "architecture" ? 6 : 4}
              onChange={(e) => update({ [key]: e.target.value })}
            />
          ))}
          <TextAreaField
            id="idea-links"
            label={f("links")}
            hint={t("linksHint")}
            value={state.links}
            rows={3}
            inputMode="url"
            spellCheck={false}
            autoCapitalize="none"
            error={linkProblem ? issueMessage({ field: "links", code: linkProblem }) : undefined}
            onChange={(e) => update({ links: e.target.value })}
          />
          <Attachments attachments={attachments} onChange={setAttachments} ensureId={ensureId} />
        </section>
      ) : null}

      {step === 3 ? (
        <Review
          state={state}
          niches={props.niches}
          attachments={attachments.length}
          links={linkLines(state.links).length}
          checklist={publishing.kind === "idle" ? [] : checklist}
          issues={issues}
          text={text}
          confirmed={confirmed}
          showUnconfirmed={publishing.kind !== "idle"}
          onConfirm={(key, value) => setConfirmed((current) => ({ ...current, [key]: value }))}
          onGoTo={goTo}
          publishing={publishing}
        />
      ) : null}

      <div className="flex flex-col-reverse gap-3 border-t border-line pt-6 sm:flex-row sm:items-center sm:justify-between">
        {step > 1 ? (
          <Button variant="secondary" onClick={() => goTo((step - 1) as Step)}>
            {t("back")}
          </Button>
        ) : (
          <span className="hidden sm:block" />
        )}
        {step < 3 ? (
          <Button variant="primary" onClick={() => goTo((step + 1) as Step)}>
            {t("continue")}
          </Button>
        ) : (
          <Button variant="primary" busy={publishing.kind === "busy"} onClick={() => void doPublish()}>
            {publishing.kind === "busy" ? t("publishing") : t("publish")}
          </Button>
        )}
      </div>
    </fieldset>
  );
}

/** "Saving…", "Saved", "Not saved yet" with a retry: icon + words, announced politely. */
function SaveStatus({ save, onRetry }: { save: Save; onRetry: () => void }) {
  const t = useTranslations("ideaEditor");
  const failed = save.kind === "failed";
  const text =
    save.kind === "saving"
      ? t("saving")
      : save.kind === "saved"
        ? save.partial
          ? t("savedExcept")
          : t("saved")
        : save.kind === "dirty" || failed
          ? t("notSaved")
          : null;
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-x-4">
      <p role="status" className={cn("inline-flex items-center gap-1.5 text-sm", failed ? "text-error" : "text-ink-soft")}>
        {save.kind === "saved" && !save.partial ? <CheckIcon className="size-4 shrink-0 text-ok" /> : null}
        {failed ? <AlertIcon className="size-4 shrink-0" /> : null}
        {text}
      </p>
      {failed ? (
        <Button variant="link" className="text-sm" onClick={onRetry}>
          {t("retrySave")}
        </Button>
      ) : null}
    </div>
  );
}
