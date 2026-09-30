"use client";

import { useEffect, useId, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";

import * as assistantCalls from "../assistant";
import {
  statusKey,
  type AssistantCalls,
  type AssistantConsent,
  type AssistantProblem,
  type AssistantSuggestion,
  type PlacementHint,
  type SuggestedTeaser,
} from "../assistant";
import type { EditorState } from "../ideas";
import type { SaveProblem } from "../outcomes";

/** Problems the panel finds before any call, apart from the API's. */
type PanelProblem = AssistantProblem | "noText" | "notSaved";

/** Where focus goes after a render: the answer's heading, or the notice that replaced the button just pressed. */
type FocusTarget = "heading" | "notice" | null;

/** Message keys under ideaFields.* for the fields a placement hint can name. */
const FIELD_KEY = {
  title: "title",
  problem_statement: "problemStatement",
  impact_claims: "impactClaims",
  summary: "summary",
  approach: "approach",
  architecture: "architecture",
  pricing: "pricing",
  notes: "notes",
} as const satisfies Record<PlacementHint["field"], string>;

export interface AssistantPanelProps {
  /** What the title and summary hold now (the "Now" column). */
  state: Pick<EditorState, "title" | "summary">;
  /** The proposal's id, once a save has made the draft. */
  getId: () => string | null;
  /** The editor's save: the assistant reads the saved draft, so everything typed is saved first. */
  saveAll: () => Promise<SaveProblem | null>;
  /** Puts a suggestion into the title and summary through the editor's own change handler (and so its autosave). */
  onUse: (teaser: SuggestedTeaser) => void;
  /** Closes the panel; the editor gives focus back to its button. */
  onClose: () => void;
  calls?: AssistantCalls;
}

/**
 * "Suggest a clearer teaser" (REQ-PROP-05; docs/spec/06 6.3, docs/spec/09). Opening the panel asks at once. The first
 * time in a sign-in, a dialog shows the API's consent wording verbatim and sends its version back when the owner turns
 * the assistant on; "Not now" (or Escape) closes the panel and nothing is sent. The answer shows the suggested title
 * and summary beside the current ones, labelled "AI-drafted" (and "Demo fallback" when no model wrote it), with any
 * placement hints. Nothing changes until the owner presses "Use this", which goes through the editor's own save.
 * Every refusal has a fixed sentence of its own; the API's messages are never shown.
 */
export function AssistantPanel({
  state,
  getId,
  saveAll,
  onUse,
  onClose,
  calls = assistantCalls,
}: AssistantPanelProps) {
  const t = useStrings("ideaAssistant");
  const f = useStrings("ideaFields");
  const [consent, setConsent] = useState<AssistantConsent | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogProblem, setDialogProblem] = useState<AssistantProblem | null>(null);
  const [granting, setGranting] = useState(false);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<PanelProblem | null>(null);
  const [answer, setAnswer] = useState<AssistantSuggestion | null>(null);
  const [notice, setNotice] = useState<"applied" | "off" | null>(null);
  const [turningOff, setTurningOff] = useState(false);

  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const accepted = useRef(false); // the dialog closed because the owner turned the assistant on
  const started = useRef(false);
  const busy = useRef(false); // one request at a time, whatever the renders in between
  const focusTo = useRef<FocusTarget>(null); // read after the render that shows the target
  const titleId = useId();
  const bodyId = useId();
  const headingId = useId();

  function openDialog(why: AssistantProblem | null) {
    accepted.current = false;
    setDialogProblem(why);
    setDialogOpen(true);
  }

  /** Asks for one suggestion; the consent was checked by the caller. */
  async function request(id: string) {
    setWorking(true);
    const result = await calls.suggest(id);
    setWorking(false);
    if (result.ok) {
      setAnswer(result.value);
      focusTo.current = "heading";
      return;
    }
    if (result.problem === "consentRequired") {
      // The opt-in ended since it was read (signed out elsewhere, or turned off in another tab): ask again.
      const read = await calls.consentState(id);
      if (read.ok) {
        setConsent(read.value);
        openDialog("consentRequired");
        return;
      }
      setProblem(read.problem);
      return;
    }
    setProblem(result.problem);
  }

  async function ask() {
    if (busy.current) return;
    busy.current = true;
    try {
      setProblem(null);
      setNotice(null);
      if (!state.title.trim() && !state.summary.trim()) {
        setProblem("noText");
        return;
      }
      setWorking(true);
      // The assistant reads the saved draft: what is on the screen is saved first, or nothing is asked.
      const saved = await saveAll();
      const id = getId();
      if (saved || !id) {
        setWorking(false);
        setProblem(saved ? "notSaved" : "failed");
        return;
      }
      if (!consent?.granted) {
        const read = await calls.consentState(id);
        if (!read.ok) {
          setWorking(false);
          setProblem(read.problem);
          return;
        }
        setConsent(read.value);
        if (!read.value.granted) {
          setWorking(false);
          openDialog(null);
          return;
        }
      }
      await request(id);
    } finally {
      busy.current = false;
    }
  }

  async function grant() {
    const id = getId();
    if (granting || !consent || !id) return;
    setGranting(true);
    setDialogProblem(null);
    const result = await calls.grantConsent(id, consent.version);
    if (!result.ok) {
      if (result.problem === "consentTextChanged") {
        // The wording changed since it was shown: show the new one, whose version the next press sends.
        const read = await calls.consentState(id);
        if (read.ok) setConsent(read.value);
      }
      setGranting(false);
      setDialogProblem(result.problem);
      return;
    }
    setGranting(false);
    setConsent(result.value);
    accepted.current = true;
    setDialogOpen(false);
    focusTo.current = "heading";
    busy.current = true;
    try {
      await request(id);
    } finally {
      busy.current = false;
    }
  }

  async function turnOff() {
    const id = getId();
    if (turningOff || !id) return;
    setTurningOff(true);
    setProblem(null);
    const result = await calls.withdrawConsent(id);
    setTurningOff(false);
    if (!result.ok) {
      setProblem(result.problem);
      return;
    }
    setConsent(result.value);
    setNotice("off");
    focusTo.current = "notice";
  }

  function use(teaser: SuggestedTeaser) {
    onUse(teaser);
    setNotice("applied");
    focusTo.current = "notice";
  }

  // Opening the panel is the request: ask once (a ref, so a development double effect does not ask twice).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void ask();
    // ask reads this render's props; the panel asks again only when the owner presses "Ask again".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The native dialog follows dialogOpen: showModal traps focus and makes the rest of the page inert. Focus starts on
  // "Not now", the choice that sends nothing (React never renders the autofocus attribute on the client).
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (dialogOpen && !node.open) {
      node.showModal();
      node.querySelector<HTMLButtonElement>("[data-dialog-cancel]")?.focus();
    }
    if (!dialogOpen && node.open) node.close();
  }, [dialogOpen]);

  // After the render that shows it: the answer's heading, or the notice that replaced the button just pressed.
  useEffect(() => {
    const target = focusTo.current;
    if (!target) return;
    focusTo.current = null;
    (target === "heading" ? heading.current : noticeRef.current)?.focus();
  });

  const teaser = answer?.teaser ?? null;
  const key = answer ? statusKey(answer) : null;
  const granted = consent?.granted === true;

  return (
    <div id="assistant-panel" className="flex flex-col gap-5 rounded-panel border border-line bg-field p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h4 id={headingId} ref={heading} tabIndex={-1} className="font-semibold text-ink focus:outline-none">
            {t("heading")}
          </h4>
          {/* The labels docs/spec/09 requires on AI output: at most two (docs/spec/07 item 2). */}
          {answer?.ai_drafted ? <Label>{t("aiDrafted")}</Label> : null}
          {answer?.demo_fallback ? <Label quiet>{t("demoFallback")}</Label> : null}
        </div>
        <Button variant="link" className="text-sm" onClick={onClose}>
          {t("close")}
        </Button>
      </div>

      <p role="status" className={cn("text-ink-soft", !working && "sr-only")}>
        {working ? t("working") : ""}
      </p>

      {problem ? <Alert>{t(`problem.${problem}`)}</Alert> : null}
      {notice ? (
        <Alert tone="ok" ref={noticeRef}>
          {t(notice === "applied" ? "applied" : "offNotice")}
        </Alert>
      ) : null}

      {key && !working ? <p className="text-ink">{t(`status.${key}`)}</p> : null}

      {teaser && !working ? (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Teaser caption={t("now")} title={state.title} summary={state.summary} />
            <Teaser caption={t("suggested")} title={teaser.title} summary={teaser.summary} suggested />
          </div>
          {notice === "applied" ? null : (
            <Button variant="secondary" className="self-start" onClick={() => use(teaser)}>
              {t("use")}
            </Button>
          )}
        </div>
      ) : null}

      {answer && answer.placement.length > 0 && !working ? (
        <section aria-labelledby={`${headingId}-placement`} className="flex flex-col gap-3">
          <h5 id={`${headingId}-placement`} className="font-semibold text-ink">
            {t("placementTitle")}
          </h5>
          <ul className="flex flex-col gap-3">
            {answer.placement.map((hint) => (
              <li key={hint.field} className="border-l-2 border-line pl-3">
                <p className="text-ink">
                  {t(hint.move === "to_tier2" ? "toTier2" : "toTier1", { name: f(FIELD_KEY[hint.field]) })}
                </p>
                <p className="mt-0.5 text-sm [overflow-wrap:anywhere] text-ink-soft">{hint.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {!working && (answer || problem || notice) ? (
        <div className="flex flex-col gap-2 border-t border-line pt-4 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6">
          <Button variant="secondary" className="self-start" onClick={() => void ask()}>
            {t("askAgain")}
          </Button>
          {granted ? (
            <Button variant="link" className="self-start text-left" busy={turningOff} onClick={() => void turnOff()}>
              {turningOff ? t("turningOff") : t("turnOff")}
            </Button>
          ) : null}
        </div>
      ) : null}

      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        // While the assistant is being turned on the dialog stays open: Escape and "Not now" wait for the answer.
        onCancel={(event) => {
          if (granting) event.preventDefault();
        }}
        onClose={() => {
          setDialogOpen(false);
          if (!accepted.current) onClose(); // "Not now" or Escape: nothing was sent, and the panel closes
        }}
        className={cn(
          "m-auto w-[calc(100%-2rem)] max-w-lg rounded-panel border border-line bg-paper p-6 text-ink",
          "backdrop:bg-[color-mix(in_oklab,var(--ink)_45%,transparent)]",
        )}
      >
        <h2 id={titleId} className="text-lg text-ink">
          {t("dialog.title")}
        </h2>
        {/* The consent wording is the API's, shown as it is: its version is what "Turn on" sends back. */}
        <p id={bodyId} data-consent-version={consent?.version} className="mt-3 whitespace-pre-line text-ink">
          {consent?.text}
        </p>
        {dialogProblem ? <Alert className="mt-4">{t(`problem.${dialogProblem}`)}</Alert> : null}
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" busy={granting} onClick={() => dialog.current?.close()} data-dialog-cancel="">
            {t("dialog.cancel")}
          </Button>
          {/* Styled as the dialog's main button but not the screen's primary action (data-primary stays on the page's). */}
          <button
            type="button"
            onClick={() => void grant()}
            aria-disabled={granting || undefined}
            className={buttonClass("primary")}
          >
            {granting ? t("dialog.busy") : t("dialog.confirm")}
          </button>
        </div>
      </dialog>
    </div>
  );
}

/** A label on AI output: an outlined tag with words (never colour alone). */
function Label({ children, quiet = false }: { children: string; quiet?: boolean }) {
  return (
    <span
      data-chip=""
      className={cn(
        "inline-flex items-center rounded-control border px-2 py-0.5 text-sm font-semibold",
        quiet ? "border-ink-soft text-ink-soft" : "border-jacaranda text-jacaranda",
      )}
    >
      {children}
    </span>
  );
}

/** One side of the comparison: a title and a summary under a caption. */
function Teaser({
  caption,
  title,
  summary,
  suggested = false,
}: {
  caption: string;
  title: string;
  summary: string;
  suggested?: boolean;
}) {
  const t = useStrings("ideaAssistant");
  const f = useStrings("ideaFields");
  const value = (text: string) =>
    text.trim() ? (
      <dd className="whitespace-pre-line [overflow-wrap:anywhere] text-ink">{text}</dd>
    ) : (
      <dd className="text-ink-soft">{t("notWritten")}</dd>
    );
  return (
    <div
      data-teaser={suggested ? "suggested" : "now"}
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-control p-4",
        suggested ? "bg-jacaranda-wash" : "border border-line",
      )}
    >
      <p className={cn("text-sm font-semibold", suggested ? "text-jacaranda" : "text-ink-soft")}>{caption}</p>
      <dl className="flex flex-col gap-3">
        <div>
          <dt className="text-sm text-ink-soft">{f("title")}</dt>
          {value(title)}
        </div>
        <div>
          <dt className="text-sm text-ink-soft">{f("summary")}</dt>
          {value(summary)}
        </div>
      </dl>
    </div>
  );
}
