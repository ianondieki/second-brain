"use client";

import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

import * as checksCalls from "../checks";
import {
  chipsOf,
  overlapKey,
  type CheckProblem,
  type ChecksCalls,
  type DisclosureCheck,
  type Originality,
} from "../checks";
import type { EditorState } from "../ideas";
import type { SaveProblem } from "../outcomes";
import { CheckAnswer, type CheckAnswerProps } from "./CheckAnswer";

// Loads when the owner first presses a check (editor/checks-load.test.tsx fails if the editor imports it): the editor
// sits at its 150 KB budget (docs/spec/07 item 5).

export type CheckKind = "overlap" | "disclosure";

/** Each check's answer and whether it is running: replaced, never changed, on every update. */
export interface ChecksSnapshot {
  answers: Partial<Record<CheckKind, CheckAnswerProps>>;
  working: Partial<Record<CheckKind, boolean>>;
}

/**
 * What the card keeps while the owner visits the other steps: the editor holds the object and the card is redrawn. A
 * check keeps running when its card goes; the card drawn next reads its state here and hears when it changes.
 */
export interface ChecksMemory {
  /** The check whose button opened the card: it runs once, as the card appears. */
  start?: CheckKind;
  snapshot?: ChecksSnapshot;
  listeners?: Set<() => void>;
}

const NOTHING: ChecksSnapshot = { answers: {}, working: {} };

export interface ChecksProps {
  /** The editor's memory of the card (the same object every time). */
  memory: () => ChecksMemory;
  /** The four teaser fields as they are now: a teaser with no text is not sent. */
  state: Pick<EditorState, "title" | "problemStatement" | "summary" | "impactClaims">;
  /** The proposal's id, once a save has made the draft. */
  getId: () => string | null;
  /** The editor's save: both checks read the saved draft, so everything typed is saved first. */
  saveAll: () => Promise<SaveProblem | null>;
  /** Today's last overlap check, drawn on the server; it stays until the overlap check runs again. */
  lastOverlap?: ReactNode;
  calls?: ChecksCalls;
}

/** Problems worded by the writing assistant's own sentences (the same codes, docs/spec/09 refusals). */
const SHARED = [
  "assistant_budget",
  "assistant_paused",
  "assistant_off",
  "signedOut",
  "mfaRequired",
  "rateLimited",
  "notFound",
  "network",
  "failed",
] as const;
type Shared = (typeof SHARED)[number];
const isShared = (why: string): why is Shared => (SHARED as readonly string[]).includes(why);

/**
 * "Teaser checks" (REQ-PROP-04, REQ-REPO-01): "Check overlap" answers with a band in words, never a score; "Check what
 * it gives away" warns when the teaser reads like how the project works. Each answers in place, in its own polite
 * live region; neither is the screen's primary action, and nothing here blocks publishing.
 */
export function Checks({ memory, state, getId, saveAll, lastOverlap, calls = checksCalls }: ChecksProps) {
  const c = useStrings("ideaChecks");
  const a = useStrings("ideaAssistant");
  const { answers, working } = useSyncExternalStore(
    (listener) => {
      const kept = memory();
      (kept.listeners ??= new Set()).add(listener);
      return () => kept.listeners?.delete(listener);
    },
    () => memory().snapshot ?? NOTHING,
    () => NOTHING,
  );

  const chips = (answer: { ai_drafted: boolean; demo_fallback: boolean }) =>
    chipsOf(answer).map((chip) => ({ label: a(chip), quiet: chip === "demoFallback" }));

  const problem = (why: CheckProblem | "noText" | "notSaved"): CheckAnswerProps => ({
    tone: "problem",
    sentence: isShared(why) ? a(`problem.${why}`) : c(`problem.${why}`),
  });

  const overlapAnswer = (answer: Originality): CheckAnswerProps => ({
    tone: answer.band === "none" ? "clear" : "note",
    sentence: c(overlapKey(answer), { count: answer.compared }),
    detail: answer.explanation,
    chips: chips(answer),
  });

  function disclosureAnswer(answer: DisclosureCheck): CheckAnswerProps {
    if (answer.flagged) {
      // The fields as words, joined the language's own way ("title and summary"), never by concatenation.
      const lang = document.documentElement.lang || "en";
      const fields = new Intl.ListFormat(lang, { type: "conjunction" }).format(
        answer.fields.map((field) => a(`field.${field}`).toLocaleLowerCase(lang)),
      );
      return {
        tone: "note",
        sentence: answer.fields.length ? c("disclosure.flagged", { fields }) : c("disclosure.flaggedAny"),
        // The model's own reason only when it wrote one (labelled); otherwise the fixed advice.
        detail: answer.ai_drafted && answer.why ? answer.why : c("disclosure.advice"),
        chips: chips(answer),
      };
    }
    if (answer.source === "model") return { tone: "clear", sentence: c("disclosure.clear"), chips: chips(answer) };
    if (answer.demo_fallback) return { tone: "note", sentence: c("disclosure.demo"), chips: chips(answer) };
    // No text, a suspected injection or a provider that is down: the API keeps the reason to itself.
    return { tone: "note", sentence: c("disclosure.unchecked") };
  }

  /** Updates the editor's copy and tells whichever card is drawn now (this one may be gone by then). */
  function update(kind: CheckKind, running: boolean, answer?: CheckAnswerProps) {
    const kept = memory();
    const now = kept.snapshot ?? NOTHING;
    kept.snapshot = {
      answers: answer ? { ...now.answers, [kind]: answer } : now.answers,
      working: { ...now.working, [kind]: running },
    };
    kept.listeners?.forEach((listener) => listener());
  }

  const show = (kind: CheckKind, answer: CheckAnswerProps) => update(kind, false, answer);

  async function run(kind: CheckKind) {
    if (memory().snapshot?.working[kind]) return; // one at a time, even across a redrawn card
    update(kind, true);
    try {
      const { title, problemStatement, summary, impactClaims } = state;
      if (![title, problemStatement, summary, impactClaims].some((text) => text.trim())) return show(kind, problem("noText"));
      // Both checks read the saved draft: what is on the screen is saved first, or nothing is checked.
      const saved = await saveAll();
      const id = getId();
      if (saved || !id) return show(kind, problem(saved ? "notSaved" : "failed"));
      if (kind === "overlap") {
        const result = await calls.overlap(id);
        show(kind, result.ok ? overlapAnswer(result.value) : problem(result.problem));
      } else {
        const result = await calls.disclosure(id);
        show(kind, result.ok ? disclosureAnswer(result.value) : problem(result.problem));
      }
    } finally {
      update(kind, false);
    }
  }

  // The card appeared because a check was pressed: that check runs once, and its button keeps the focus.
  useEffect(() => {
    const kept = memory();
    const start = kept.start;
    kept.start = undefined;
    if (!start) return;
    document.getElementById(`check-${start}`)?.focus();
    void run(start);
    // run reads this render's props; later presses go through the buttons.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const row = (kind: CheckKind, label: string, checking: string, fallback?: ReactNode) => (
    <div className="flex flex-col items-start">
      <Button id={`check-${kind}`} busy={working[kind]} onClick={() => void run(kind)}>
        {label}
      </Button>
      {/* Polite, never an alert: an answer is information, not an error (role=status). */}
      <div role="status" data-check={kind} className="not-empty:mt-3">
        {working[kind] ? (
          <p className="text-ink-soft">{checking}</p>
        ) : answers[kind] ? (
          <CheckAnswer {...answers[kind]} />
        ) : (
          fallback
        )}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      {row("overlap", c("overlapButton"), c("checkingOverlap"), lastOverlap)}
      {row("disclosure", c("disclosureButton"), c("checkingDisclosure"))}
    </div>
  );
}
