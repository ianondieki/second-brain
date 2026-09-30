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
  type SuggestedTeaser,
} from "../assistant";
import type { EditorState } from "../ideas";
import type { SaveProblem } from "../outcomes";

// Kept lean on purpose: this chunk loads on top of an editor close to its 150 KB budget (docs/spec/07 item 5).

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
  const [consent, setConsent] = useState<AssistantConsent | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogProblem, setDialogProblem] = useState<AssistantProblem | null>(null);
  const [granting, setGranting] = useState(false);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<AssistantProblem | "noText" | "notSaved" | null>(null);
  const [answer, setAnswer] = useState<AssistantSuggestion | null>(null);
  const [notice, setNotice] = useState<"applied" | "undone" | "offNotice" | null>(null);
  const [before, setBefore] = useState<SuggestedTeaser | null>(null); // the owner's words, while a suggestion is in
  const [turningOff, setTurningOff] = useState(false);

  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const problemRef = useRef<HTMLDivElement>(null);
  const accepted = useRef(false); // the dialog closed because the owner turned the assistant on
  const started = useRef(false);
  const busy = useRef(false); // one request at a time, whatever the renders in between
  const focusTo = useRef<"heading" | "notice" | "problem">(undefined); // read after the render that shows it
  const titleId = useId();
  const bodyId = useId();

  /** A refusal: its sentence, with focus on it (the button pressed may be gone). */
  function fail(why: typeof problem) {
    setProblem(why);
    focusTo.current = "problem";
  }

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
    } else if (result.problem === "consent_required") {
      // The opt-in ended since it was read (signed out elsewhere, or turned off in another tab): ask again.
      const read = await calls.consentState(id);
      if (!read.ok) return fail(read.problem);
      setConsent(read.value);
      openDialog("consent_required");
    } else fail(result.problem);
  }

  async function ask() {
    if (busy.current) return;
    busy.current = true;
    setProblem(null);
    setNotice(null);
    setAnswer(null); // a new ask: the last answer goes, so a refusal never shows it again
    setBefore(null);
    // "Ask again" hides while the request runs (and the editor's button is gone): focus waits on the heading.
    heading.current?.focus();
    try {
      if (!state.title.trim() && !state.summary.trim()) return fail("noText");
      setWorking(true);
      // The assistant reads the saved draft: what is on the screen is saved first, or nothing is asked.
      const saved = await saveAll();
      const id = getId();
      if (saved || !id) {
        setWorking(false);
        return fail(saved ? "notSaved" : "failed");
      }
      if (!consent?.granted) {
        const read = await calls.consentState(id);
        setWorking(false);
        if (!read.ok) return fail(read.problem);
        setConsent(read.value);
        if (!read.value.granted) return openDialog(null);
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
      let why = result.problem;
      if (why === "consent_text_changed") {
        // The wording changed since it was shown: show the new one, whose version the next press sends. When it cannot
        // be read, the old wording goes and "Turn on" stays off until the panel is opened again and reads it.
        const read = await calls.consentState(id);
        setConsent(read.ok ? read.value : null);
        if (!read.ok) why = read.problem;
      }
      setGranting(false);
      return setDialogProblem(why);
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
    if (!result.ok) return fail(result.problem);
    setConsent(result.value);
    setAnswer(null); // the assistant is off: its last answer goes with it
    setNotice("offNotice");
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
    const node = dialog.current!;
    if (dialogOpen && !node.open) {
      node.showModal();
      node.querySelector<HTMLElement>("[data-dialog-cancel]")?.focus();
    }
    if (!dialogOpen && node.open) node.close();
  }, [dialogOpen]);

  // After the render that shows it: the answer's heading, a refusal, or the notice that replaced the button pressed.
  useEffect(() => {
    const to = focusTo.current;
    focusTo.current = undefined;
    ({ heading, notice: noticeRef, problem: problemRef })[to!]?.current?.focus();
  });

  const teaser = !working && answer?.teaser;
  const key = !working && answer && statusKey(answer);
  const side = (caption: string, { title, summary }: SuggestedTeaser, suggested?: boolean) => (
    <div
      data-teaser={suggested ? "suggested" : before ? "before" : "now"}
      className={cn("min-w-0 rounded-control p-4", suggested ? "bg-jacaranda-wash" : "border border-line")}
    >
      <p className={cn("mb-3 text-sm font-semibold", suggested ? "text-jacaranda" : "text-ink-soft")}>{caption}</p>
      <dl>
        {[
          [t("field.title"), title],
          [t("field.summary"), summary],
        ].map(([label, text]) => (
          <div key={label} className="mb-2 [overflow-wrap:anywhere]">
            <dt className="text-sm text-ink-soft">{label}</dt>
            <dd className={text.trim() ? "whitespace-pre-line" : "text-ink-soft"}>{text.trim() ? text : t("notWritten")}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
  // The labels docs/spec/09 requires on AI output: at most two (docs/spec/07 item 2).
  const chip = (text: string, quiet?: boolean) => (
    <span
      data-chip=""
      className={cn(
        "rounded-control border px-2 py-0.5 text-sm font-semibold",
        quiet ? "border-ink-soft text-ink-soft" : "border-jacaranda text-jacaranda",
      )}
    >
      {text}
    </span>
  );

  return (
    <div id="assistant-panel" className="flex flex-col gap-5 rounded-panel border border-line bg-field p-4 text-ink sm:p-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h4 ref={heading} tabIndex={-1} className="font-semibold focus:outline-none">
          {t(teaser ? "heading" : "headingAnswer")}
        </h4>
        {answer?.ai_drafted && chip(t("aiDrafted"))}
        {answer?.demo_fallback && chip(t("demoFallback"), true)}
        <Button variant="link" className="ml-auto text-sm" onClick={onClose}>
          {t("close")}
        </Button>
      </div>

      <p role="status" className={working ? "text-ink-soft" : "sr-only"}>
        {working && t("working")}
      </p>
      {problem && <Alert ref={problemRef}>{t(`problem.${problem}`)}</Alert>}
      {notice && (
        <Alert tone="ok" ref={noticeRef}>
          {t(notice)}
        </Alert>
      )}
      {key && <p>{t(`status.${key}`)}</p>}

      {teaser && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {/* Once the suggestion is in, the owner's own words stay beside it as "Before", and "Undo" puts them back. */}
            {side(t(before ? "before" : "now"), before ?? state)}
            {side(t("suggested"), teaser, true)}
          </div>
          <Button
            variant={before ? "link" : "secondary"}
            className="self-start"
            onClick={() => {
              onUse(before ?? teaser);
              setBefore(before ? null : { title: state.title, summary: state.summary });
              setNotice(before ? "undone" : "applied");
              focusTo.current = "notice";
            }}
          >
            {t(before ? "undo" : "use")}
          </Button>
        </>
      )}

      {!working && !!answer?.placement.length && (
        <div>
          <h5 className="font-semibold">{t("placementTitle")}</h5>
          <ul className="mt-3 flex flex-col gap-3">
            {answer.placement.map((hint) => (
              <li key={hint.field} className="border-l-2 border-line pl-3 [overflow-wrap:anywhere]">
                {t(hint.move === "to_tier2" ? "toTier2" : "toTier1", { name: t(`field.${hint.field}`) })}
                <p className="mt-0.5 text-sm text-ink-soft">{hint.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!working && (answer || problem || notice) && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-4">
          {/* Turned off: asking again means turning it on (the dialog shows the wording first). */}
          <Button onClick={() => void ask()}>{t(consent?.granted === false ? "dialog.confirm" : "askAgain")}</Button>
          {consent?.granted && (
            <Button variant="link" className="text-left" busy={turningOff} onClick={() => void turnOff()}>
              {t(turningOff ? "turningOff" : "turnOff")}
            </Button>
          )}
        </div>
      )}

      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        // While the assistant is being turned on the dialog stays open: Escape and "Not now" wait for the answer.
        onCancel={(event) => granting && event.preventDefault()}
        onClose={() => {
          setDialogOpen(false);
          if (!accepted.current) onClose(); // "Not now" or Escape: nothing was sent, and the panel closes
        }}
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-panel border border-line bg-paper p-6 text-ink backdrop:bg-scrim"
      >
        <h2 id={titleId} className="text-lg">
          {t("dialog.title")}
        </h2>
        {/* The consent wording is the API's, shown as it is: its version is what "Turn on" sends back. */}
        <p id={bodyId} data-consent-version={consent?.version} className="my-4 whitespace-pre-line">
          {consent?.text}
        </p>
        {dialogProblem && <Alert>{t(`problem.${dialogProblem}`)}</Alert>}
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button busy={granting} onClick={() => dialog.current?.close()} data-dialog-cancel="">
            {t("dialog.cancel")}
          </Button>
          {/* Styled as the dialog's main button but not the screen's primary action (data-primary stays on the page's). */}
          <button
            type="button"
            onClick={() => void grant()}
            aria-disabled={granting || !consent || undefined}
            className={buttonClass("primary")}
          >
            {t(granting ? "dialog.busy" : "dialog.confirm")}
          </button>
        </div>
      </dialog>
    </div>
  );
}
