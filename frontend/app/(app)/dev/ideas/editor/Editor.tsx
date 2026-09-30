"use client";

import { Component, Suspense, use, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon } from "@/components/ui/status-icons";
import { SelectField } from "@/components/ui/SelectField";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";
import { preloadable } from "@/lib/preloadable";

import type { AssistantCalls } from "../assistant";
import type { Calls } from "../calls";
import {
  ASKS,
  editHref,
  LIMITS,
  MATURITIES,
  MATURITY_KEY,
  MAX_SUMMARY_WORDS,
  publishChecklist,
  wordCount,
  type Attachment,
  type AttestationText,
  type County,
  type EditorState,
  type FieldIssue,
  type FieldName,
  type NicheNode,
  type ProblemCard,
  type Step,
} from "../ideas";
import type { SaveProblem } from "../outcomes";
import { useIssueMessage } from "./issues";
import { preloadPanels, ProblemPicker } from "./ProblemPicker";
import { Stepper } from "./Stepper";

// Steps 2 and 3 load when they are opened, not with the page (docs/spec/07 item 5: at most 150 KB of JS per route;
// React.lazy, as in settings/security/lazy.ts, adds no runtime).
// Server-rendered whole (preloadable), so the HTML arrives complete and nothing shifts while the chunk loads.
const detailsModule = preloadable(() => import("./DetailsStep"));
const reviewModule = preloadable(() => import("./Review"));

/** Starts loading the later steps' code (tests render them at once). */
export function preloadSteps() {
  return Promise.all([detailsModule(), reviewModule(), preloadPanels()]);
}

function DetailsStep(props: ComponentProps<typeof import("./DetailsStep").DetailsStep>) {
  const { DetailsStep: Step } = use(detailsModule());
  return <Step {...props} />;
}

function Review(props: ComponentProps<typeof import("./Review").Review>) {
  const { Review: Step } = use(reviewModule());
  return <Step {...props} />;
}

// The writing assistant's panel (REQ-PROP-05) loads when the owner opens it: closed, it costs this page one button.
// Never import it statically (editor/assistant-load.test.tsx fails if it is): its code would join the page's.
const loadAssistant = () => preloadable(() => import("./AssistantPanel"));
let assistantModule = loadAssistant();

/** Starts loading the assistant panel's code (tests render it at once). */
export function preloadAssistant() {
  return assistantModule();
}

function AssistantPanel(props: ComponentProps<typeof import("./AssistantPanel").AssistantPanel>) {
  const { AssistantPanel: Panel } = use(assistantModule());
  return <Panel {...props} />;
}

/** A panel whose code did not load (offline) or broke: the editor stays, and the next press loads it afresh. */
class PanelBoundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    assistantModule = loadAssistant(); // a rejected load is kept by preloadable: start a new one
    this.props.onError();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export interface EditorProps {
  /** The proposal's id; null for a new idea (the first save creates it). */
  id: string | null;
  /** The proposal has a draft version. A published one without a draft shows its registered version's files; the
   * first save or file action drafts the next version, whose copies of those files have new ids. */
  hasDraft?: boolean;
  initial: EditorState;
  attachments: Attachment[];
  step: Step;
  niches: NicheNode[];
  counties: County[];
  attestations: AttestationText;
  problems: ProblemCard[];
  calls?: Calls;
  /** The writing assistant's calls (tests pass fakes; the panel loads the real ones when it opens). */
  assistant?: AssistantCalls;
}

type Save =
  | { kind: "clean" }
  | { kind: "dirty" }
  | { kind: "saving" }
  | { kind: "saved"; partial: boolean }
  | { kind: "failed"; problem: SaveProblem };

const AUTOSAVE_MS = 1200;

// The API calls load with the first save, search or publish, not with the page: nothing is sent before someone types
// (docs/spec/07 item 5, the 150 KB budget; the same on-demand pattern as settings/security/lazy.ts).
const loadCalls = (): Promise<Calls> => import("../calls");
// The first save needs only the save path (a smaller chunk than all the calls).
const loadSave = (): Promise<Pick<Calls, "saveState">> => import("../save");

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
  const t = useStrings("ideaEditor");
  const f = useStrings("ideaFields");
  const assistantT = useStrings("ideaAssistant");
  const issueMessage = useIssueMessage();
  const injected = props.calls;
  const getCalls = () => (injected ? Promise.resolve(injected) : loadCalls());

  const [state, setState] = useState<EditorState>(props.initial);
  const [step, setStep] = useState<Step>(props.step);
  const [attachments, setAttachments] = useState<Attachment[]>(props.attachments);
  const [save, setSave] = useState<Save>({ kind: "clean" });
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [showRequired, setShowRequired] = useState(false);
  const [created, setCreated] = useState(props.id !== null);
  const [publishing, setPublishing] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantFailed, setAssistantFailed] = useState(false);

  const idRef = useRef<string | null>(props.id);
  const draftRef = useRef(props.hasDraft ?? props.id !== null);
  const attachmentsRef = useRef(attachments); // the list as the last change left it, read by file actions
  const mounted = useRef(true);
  const fieldset = useRef<HTMLFieldSetElement>(null);
  const latest = useRef(state); // what the fields hold now, read by saves that run after a render
  const edits = useRef(0); // bumped on every change
  const savedEdits = useRef(0); // the edit count the last successful save covered
  const inFlight = useRef<Promise<SaveProblem | null> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const stepRef = useRef(step);
  const returnToAssistant = useRef(false); // the panel closed: its button takes focus once it is back

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
    setSave({ kind: "saving" });
    let result: Awaited<ReturnType<Calls["saveState"]>>;
    try {
      const save = injected ?? (await loadSave());
      result = await save.saveState(idRef.current, latest.current);
    } catch {
      // The calls' code could not be fetched (offline).
      result = { outcome: { ok: false, problem: "network", fields: [] }, held: [] };
    }
    const { outcome, held } = result;
    if (!outcome.ok) {
      setSave({ kind: "failed", problem: outcome.problem });
      if (outcome.fields.length > 0) setIssues(outcome.fields);
      return outcome.problem;
    }
    savedEdits.current = started;
    draftRef.current = true;
    if (creating) {
      idRef.current = outcome.value.id;
      setCreated(true);
      // The address now names the draft, so a reload or the back button returns to it (no navigation, no refetch).
      if (mounted.current) {
        window.history.replaceState(window.history.state, "", editHref(outcome.value.id, stepRef.current));
      }
    }
    // The draft's own files (after a published idea was drafted again, their ids are new).
    changeAttachments(() => outcome.value.draft?.confidential.attachments ?? []);
    setIssues([]);
    if (edits.current !== started) {
      setSave({ kind: "dirty" }); // typed during the save: the next one follows (at once when the editor has gone)
      if (mounted.current) schedule(AUTOSAVE_MS);
      else void flush();
    } else {
      setSave({ kind: "saved", partial: held.length > 0 });
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

  // The fields turn on once React runs, on the DOM node rather than through state: a re-render as hydration ends would
  // hand a server-rendered step that is still loading new props, and React would render it again on the client
  // (its HTML removed until the chunk arrives: a layout shift). React never re-applies the constant attributes.
  useEffect(() => {
    if (!fieldset.current) return;
    fieldset.current.disabled = false;
    fieldset.current.dataset.hydrated = "true";
  }, []);

  function closeAssistant() {
    returnToAssistant.current = true;
    setAssistantOpen(false);
  }

  useEffect(() => {
    if (assistantOpen || !returnToAssistant.current) return;
    returnToAssistant.current = false;
    document.getElementById("assistant-open")?.focus();
  }, [assistantOpen]);

  // Leaving the editor (a link, the back button) saves what was typed instead of dropping the pending autosave.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current) void flush();
    };
    // flush reads only refs, so the first render's copy stays current.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function changeAttachments(change: (list: Attachment[]) => Attachment[]) {
    attachmentsRef.current = change(attachmentsRef.current);
    setAttachments(attachmentsRef.current);
  }

  /** Makes sure the draft version exists and is saved, for a file action; its id and files, or why not. */
  async function ensureDraft(): Promise<{ id: string; attachments: Attachment[] } | { problem: SaveProblem }> {
    if ((!idRef.current || !draftRef.current) && edits.current === savedEdits.current) edits.current += 1;
    const problem = await saveAll();
    if (problem) return { problem };
    return idRef.current ? { id: idRef.current, attachments: attachmentsRef.current } : { problem: "failed" };
  }

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


  // --- issues shown by the fields ---------------------------------------------------------------------------------

  const checklist = publishChecklist(state);
  const shown: FieldIssue[] = [
    ...issues,
    ...(showRequired ? checklist.filter((c) => !issues.some((i) => i.field === c.field)) : []),
  ];
  /** Every finding for the field, one per line (the sanitiser can find a link and a phone number at once). */
  const errorFor = (field: FieldName) => {
    const found = shown.filter((i) => i.field === field);
    if (found.length === 0) return undefined;
    if (found.length === 1) return issueMessage(found[0]);
    return found.map((issue) => (
      <span key={issue.code} className="block">
        {issueMessage(issue)}
      </span>
    ));
  };
  const words = wordCount(state.summary);

  const statusLine = <SaveStatus save={save} onRetry={() => void flush()} />;

  return (
    <>
    {/* "Edit idea" from the moment the first save made the draft. */}
    <h1 className="mb-6 text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
      {created ? t("pageTitleEdit") : t("pageTitleNew")}
    </h1>
    {/* Disabled until React runs: anything typed into the server-rendered fields before then would be lost (slow
        connections take seconds to hydrate). `data-hydrated` tells tests when the editor is live. */}
    <fieldset
      ref={fieldset}
      disabled
      data-hydrated="false"
      className="m-0 flex min-w-0 flex-col gap-8 border-0 p-0"
    >
      <div className="flex flex-col gap-3">
        <Stepper step={step} onStep={goTo} disabled={publishing} />
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

          <section aria-labelledby="teaser-title" className="flex flex-col gap-6 pt-4">
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

          <section aria-labelledby="assistant-title" className="flex flex-col gap-4 pt-4">
            <div>
              <h3 id="assistant-title" className="font-semibold text-ink">
                {t("assistantTitle")}
              </h3>
              <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{t("assistantHint")}</p>
            </div>
            {assistantOpen ? (
              <PanelBoundary
                onError={() => {
                  setAssistantFailed(true);
                  closeAssistant();
                }}
              >
                <Suspense
                  fallback={
                    <p role="status" className="text-ink-soft">
                      {t("assistantOpening")}
                    </p>
                  }
                >
                  <AssistantPanel
                    state={state}
                    getId={() => idRef.current}
                    saveAll={() => {
                      // A new idea's first ask still needs a draft; a save already under way creates it.
                      if (!idRef.current && edits.current === savedEdits.current) edits.current += 1;
                      return saveAll();
                    }}
                    onUse={(teaser) => update({ title: teaser.title, summary: teaser.summary })}
                    onClose={closeAssistant}
                    calls={props.assistant}
                  />
                </Suspense>
              </PanelBoundary>
            ) : (
              <>
                {assistantFailed ? <Alert>{assistantT("problem.network")}</Alert> : null}
                <Button
                  id="assistant-open"
                  variant="secondary"
                  className="self-start"
                  onClick={() => {
                    setAssistantFailed(false);
                    setAssistantOpen(true);
                  }}
                >
                  {t("assistantOpen")}
                </Button>
              </>
            )}
          </section>
        </div>
      ) : null}

      {step === 2 ? (
        <Suspense fallback={null}>
          <DetailsStep
            state={state}
            update={update}
            attachments={attachments}
            onAttachments={changeAttachments}
            ensureDraft={ensureDraft}
            getCalls={getCalls}
          />
        </Suspense>
      ) : null}

      {step === 3 ? (
        <Suspense fallback={null}>
          <Review
            state={state}
            niches={props.niches}
            attachments={attachments.length}
            checklist={checklist}
            issues={issues}
            onIssues={setIssues}
            onShowRequired={() => setShowRequired(true)}
            initialText={props.attestations}
            saveAll={() => {
              // Publishing straight away still needs a draft; a save already under way creates it.
              if (!idRef.current && edits.current === savedEdits.current) edits.current += 1;
              return saveAll();
            }}
            getId={() => idRef.current}
            getCalls={getCalls}
            onGoTo={goTo}
            onBusy={setPublishing}
          />
        </Suspense>
      ) : (
        <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:items-center sm:justify-between">
          {step > 1 ? (
            <Button variant="secondary" onClick={() => goTo((step - 1) as Step)}>
              {t("back")}
            </Button>
          ) : (
            <span className="hidden sm:block" />
          )}
          <Button variant="primary" onClick={() => goTo((step + 1) as Step)}>
            {t("continue")}
          </Button>
        </div>
      )}
    </fieldset>
    </>
  );
}

/** "Saving…", "Saved", "Not saved yet" with a retry: icon + words, announced politely. */
function SaveStatus({ save, onRetry }: { save: Save; onRetry: () => void }) {
  const t = useStrings("ideaEditor");
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
      {/* Saving again cannot help when the API refused the content: the marked fields need changes first. */}
      {failed && save.problem !== "fields" && save.problem !== "validation" ? (
        <Button variant="link" className="text-sm" onClick={onRetry}>
          {t("retrySave")}
        </Button>
      ) : null}
    </div>
  );
}
